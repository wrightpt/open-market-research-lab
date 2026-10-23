"""Zero-funds, x402-v2-shaped sandbox exchange; NEVER real settlement.

The only accepted 'payment' is an ephemeral HMAC fixture produced in-process
by StubFacilitator. The fake asset and payee are deliberately not transferable.
"""
import hashlib
import hmac
import json
import re
import secrets
import time

from market_lab.io import LabError, canonical_bytes, object_hash
from .ledger import MeterError, PRICES
from .meter_service import OfflineResearchService
from .sandbox_identity import b64url, unb64url

NETWORK = "eip155:84532"  # Base Sepolia CAIP-2 identifier; NO chain calls
ASSET = "0x0000000000000000000000000000000000000001"  # deliberately NOT USDC
PAY_TO = "0x0000000000000000000000000000000000000002"  # NOT a merchant wallet
ATOMIC_UNITS_PER_CENT = 10_000  # emulate six-decimal USDC, NO transfers
MAX_PROOF_BYTES = 6144
MAX_CHALLENGES = 128
ID = re.compile(r"[a-f0-9]{32}\Z")
HASH = re.compile(r"[a-f0-9]{64}\Z")


class SandboxReject(LabError):
    """Code is suitable for a sanitized local HTTP error; no tokens echoed."""

    def __init__(self, code, status=400):
        super().__init__(code)
        self.status = status
        self.code = code


class StubFacilitator:
    """Ephemeral signer/verifier test fixture. NOT EIP-712, EIP-3009, or blockchain."""

    def __init__(self):
        self._secret = secrets.token_bytes(32)
        self.verify_available = True
        self.settle_available = True

    def make_test_signature(self, required, *, overrides=None):
        """Test harness only; NEVER routed to clients as a signing API."""
        accepted = required["accepts"][0]
        binding = required["extensions"]["sandbox"]
        proof = {
            "proofId": secrets.token_hex(16),
            "challengeId": binding["challengeId"],
            "nonce": binding["nonce"],
            "tenantDigest": binding["tenantDigest"],
            "requestSha256": binding["requestSha256"],
            "idempotencySha256": binding["idempotencySha256"],
            "amount": accepted["amount"],
            "network": accepted["network"],
            "asset": accepted["asset"],
            "expiresAt": binding["expiresAt"],
        }
        if overrides:
            proof.update(overrides)
        payload = {"accepted": accepted, "proof": proof}
        signature = b64url(hmac.new(
            self._secret, canonical_bytes(payload), hashlib.sha256).digest())
        return {
            "x402Version": 2,
            "accepted": accepted,
            "payload": {"sandboxProof": proof, "sandboxSignature": signature},
            "extensions": {"sandbox": {"mode": "zero_funds_stub"}},
        }

    def verify(self, payment, required):
        if not self.verify_available:
            raise SandboxReject("stub_facilitator_unavailable", 503)
        if type(payment) is not dict or set(payment) != {
            "x402Version", "accepted", "payload", "extensions"
        } or type(payment.get("x402Version")) is not int or payment["x402Version"] != 2:
            raise SandboxReject("malformed_mock_payment")
        if payment["accepted"] != required["accepts"][0]:
            raise SandboxReject("incorrect_payment_requirements")
        if payment["extensions"] != {"sandbox": {"mode": "zero_funds_stub"}}:
            raise SandboxReject("wrong_mock_payment_mode")
        payload = payment["payload"]
        if type(payload) is not dict or set(payload) != {"sandboxProof", "sandboxSignature"}:
            raise SandboxReject("malformed_mock_proof")
        proof, signature = payload["sandboxProof"], payload["sandboxSignature"]
        if type(proof) is not dict or set(proof) != {
            "proofId", "challengeId", "nonce", "tenantDigest", "requestSha256",
            "idempotencySha256", "amount", "network", "asset", "expiresAt"
        } or type(proof.get("proofId")) is not str or not ID.fullmatch(proof["proofId"]):
            raise SandboxReject("malformed_mock_proof")
        binding, accepted = required["extensions"]["sandbox"], required["accepts"][0]
        expected = {
            "challengeId": binding["challengeId"], "nonce": binding["nonce"],
            "tenantDigest": binding["tenantDigest"],
            "requestSha256": binding["requestSha256"],
            "idempotencySha256": binding["idempotencySha256"],
            "amount": accepted["amount"], "network": accepted["network"],
            "asset": accepted["asset"], "expiresAt": binding["expiresAt"],
        }
        if any(proof[key] != value for key, value in expected.items()):
            raise SandboxReject("mock_proof_binding_mismatch")
        if type(signature) is not str or len(signature) > 100:
            raise SandboxReject("invalid_mock_signature")
        try:
            actual = unb64url(signature)
        except LabError as exc:
            raise SandboxReject("invalid_mock_signature") from exc
        expected_mac = hmac.new(self._secret, canonical_bytes({
            "accepted": accepted, "proof": proof,
        }), hashlib.sha256).digest()
        if not hmac.compare_digest(actual, expected_mac):
            raise SandboxReject("invalid_mock_signature")
        return object_hash(payment), proof["proofId"]

    def settle(self, proof_hash):
        if not self.settle_available:
            raise SandboxReject("stub_settlement_unavailable", 503)
        if type(proof_hash) is not str or not HASH.fullmatch(proof_hash):
            raise SandboxReject("invalid_mock_proof_digest")
        # This is a tagged audit correlation value, NOT a transaction hash.
        return "sandbox-no-chain-" + proof_hash[:24]


class SandboxExchange:
    """Challenge/proof journal adjacent to, but distinct from, the Commons journal.

    The proof uniqueness constraint and durable execution claim are committed in
    the SAME SQLite transaction as OfflineLedger's receipt state transition.
    """

    def __init__(self, ledger, issuer, facilitator=None):
        self.ledger = ledger
        self.issuer = issuer
        self.facilitator = facilitator or StubFacilitator()
        self.service = OfflineResearchService(ledger)
        self._initialize()
        self.verify_audit()
        self.reconcile()

    def _initialize(self):
        definitions = (
            "CREATE TABLE IF NOT EXISTS sandbox_challenges("
            "id TEXT PRIMARY KEY, operation_id TEXT NOT NULL UNIQUE, "
            "tenant TEXT NOT NULL, request_hash TEXT NOT NULL, key_hash TEXT NOT NULL, "
            "nonce TEXT NOT NULL UNIQUE, resource_url TEXT NOT NULL, expires REAL NOT NULL, "
            "phase TEXT NOT NULL, proof_hash TEXT, mock_transaction TEXT)",
            "CREATE TABLE IF NOT EXISTS sandbox_proofs("
            "proof_hash TEXT PRIMARY KEY, proof_id TEXT NOT NULL UNIQUE, "
            "challenge_id TEXT NOT NULL UNIQUE, "
            "operation_id TEXT NOT NULL UNIQUE, tenant TEXT NOT NULL, "
            "request_hash TEXT NOT NULL)",
            "CREATE TRIGGER IF NOT EXISTS no_sandbox_proof_update "
            "BEFORE UPDATE ON sandbox_proofs "
            "BEGIN SELECT RAISE(ABORT, 'sandbox proof is immutable'); END",
            "CREATE TRIGGER IF NOT EXISTS no_sandbox_proof_delete "
            "BEFORE DELETE ON sandbox_proofs "
            "BEGIN SELECT RAISE(ABORT, 'sandbox proof is immutable'); END",
            "CREATE TABLE IF NOT EXISTS sandbox_events("
            "seq INTEGER PRIMARY KEY AUTOINCREMENT, payload TEXT NOT NULL, "
            "previous_hash TEXT NOT NULL, event_hash TEXT NOT NULL)",
            "CREATE TRIGGER IF NOT EXISTS no_sandbox_event_update "
            "BEFORE UPDATE ON sandbox_events "
            "BEGIN SELECT RAISE(ABORT, 'sandbox events are immutable'); END",
            "CREATE TRIGGER IF NOT EXISTS no_sandbox_event_delete "
            "BEFORE DELETE ON sandbox_events "
            "BEGIN SELECT RAISE(ABORT, 'sandbox events are immutable'); END",
        )
        with self.ledger.transaction() as db:
            for sql in definitions:
                db.execute(sql)

    def _event(self, db, challenge, phase, reason=None):
        proof = db.execute(
            "SELECT proof_id FROM sandbox_proofs WHERE challenge_id=?",
            (challenge["id"],)
        ).fetchone()
        payload = {
            "challengeId": challenge["id"], "operationId": challenge["operation_id"],
            "tenantDigest": object_hash(challenge["tenant"]),
            "requestSha256": challenge["request_hash"],
            "phase": phase, "proofSha256": challenge["proof_hash"],
            "proofIdSha256": object_hash(proof["proof_id"]) if proof else None,
            "mockTransaction": challenge["mock_transaction"],
            "reason": reason, "atMs": int(self.ledger.clock() * 1000),
        }
        last = db.execute(
            "SELECT event_hash FROM sandbox_events ORDER BY seq DESC LIMIT 1"
        ).fetchone()
        previous = last["event_hash"] if last else "0" * 64
        hashed = object_hash({"previous": previous, "payload": payload})
        db.execute("INSERT INTO sandbox_events(payload,previous_hash,event_hash) VALUES(?,?,?)",
                   (canonical_bytes(payload).decode(), previous, hashed))

    def verify_audit(self):
        with self.ledger.transaction() as db:
            previous = "0" * 64
            states = {}
            for row in db.execute("SELECT * FROM sandbox_events ORDER BY seq"):
                try:
                    payload = json.loads(row["payload"])
                    hashed = object_hash({"previous": previous, "payload": payload})
                except (ValueError, TypeError) as exc:
                    raise SandboxReject("sandbox_audit_invalid", 503) from exc
                if row["previous_hash"] != previous or row["event_hash"] != hashed:
                    raise SandboxReject("sandbox_audit_drift", 503)
                previous = hashed
                states[payload["challengeId"]] = payload
            challenges = list(db.execute("SELECT * FROM sandbox_challenges"))
            if set(states) != {row["id"] for row in challenges}:
                raise SandboxReject("sandbox_audit_projection_drift", 503)
            for row in challenges:
                record = states[row["id"]]
                if (record["phase"] != row["phase"]
                        or record["proofSha256"] != row["proof_hash"]
                        or record["requestSha256"] != row["request_hash"]
                        or record["operationId"] != row["operation_id"]):
                    raise SandboxReject("sandbox_audit_projection_drift", 503)
                proof = db.execute(
                    "SELECT * FROM sandbox_proofs WHERE challenge_id=?", (row["id"],)
                ).fetchone()
                if (proof is None) != (row["proof_hash"] is None):
                    raise SandboxReject("sandbox_proof_projection_drift", 503)
                if proof is not None and (
                    proof["proof_hash"] != row["proof_hash"]
                    or proof["operation_id"] != row["operation_id"]
                    or proof["tenant"] != row["tenant"]
                    or proof["request_hash"] != row["request_hash"]
                    or record["proofIdSha256"] != object_hash(proof["proof_id"])
                ):
                    raise SandboxReject("sandbox_proof_projection_drift", 503)
        return True

    def _change(self, db, challenge, phase, *, proof_hash=None, transaction=None,
                reason=None):
        db.execute(
            "UPDATE sandbox_challenges SET phase=?, proof_hash=COALESCE(?,proof_hash), "
            "mock_transaction=COALESCE(?,mock_transaction) WHERE id=?",
            (phase, proof_hash, transaction, challenge["id"]),
        )
        updated = db.execute(
            "SELECT * FROM sandbox_challenges WHERE id=?", (challenge["id"],)
        ).fetchone()
        self._event(db, updated, phase, reason)
        return updated

    def reconcile(self):
        """Keep challenge projection consistent with the existing ledger after restart."""
        with self.ledger.transaction() as db:
            for challenge in db.execute("SELECT * FROM sandbox_challenges").fetchall():
                operation = db.execute(
                    "SELECT state FROM operations WHERE id=? AND tenant_id=?",
                    (challenge["operation_id"], challenge["tenant"]),
                ).fetchone()
                if operation is None:
                    raise SandboxReject("missing_sandbox_operation", 503)
                target = {
                    "settled": "settled", "failed": "failed",
                    "uncertain": "uncertain", "expired": "expired",
                    "cancelled": "cancelled", "refunded": "refunded",
                }.get(operation["state"])
                if target and target != challenge["phase"]:
                    self._change(db, challenge, target, reason="ledger_reconciliation")

    def _required(self, challenge, operation):
        amount = operation["price_cents"] * ATOMIC_UNITS_PER_CENT
        return {
            "x402Version": 2,
            "error": "PAYMENT-SIGNATURE is required (sandbox stub; no real funds)",
            "resource": {
                "url": challenge["resource_url"],
                "description": "Local synthetic research fixture; zero real payment",
                "mimeType": "application/json",
            },
            "accepts": [{
                "scheme": "exact", "network": NETWORK, "amount": str(amount),
                "asset": ASSET, "payTo": PAY_TO, "maxTimeoutSeconds": 60,
                "extra": {"name": "FAKE-USDC-UNSPENDABLE", "version": "sandbox",
                          "paymentFlow": "authorization"},
            }],
            "extensions": {"sandbox": {
                "mode": "zero_funds_stub",
                "challengeId": challenge["id"], "nonce": challenge["nonce"],
                "tenantDigest": object_hash(challenge["tenant"]),
                "requestSha256": challenge["request_hash"],
                "idempotencySha256": challenge["key_hash"],
                "operationId": challenge["operation_id"],
                "expiresAt": int(challenge["expires"]),
                "catalogVersion": 1,
            }},
        }

    @staticmethod
    def _lookup(db, tenant, operation_id):
        return db.execute(
            "SELECT * FROM sandbox_challenges WHERE tenant=? AND operation_id=?",
            (tenant, operation_id),
        ).fetchone()

    def challenge(self, principal, key, sku, params, resource_url):
        tenant = self.ledger.registry.require(principal)
        receipt = self.ledger.reserve(principal, key, sku, params)
        if receipt["state"] != "reserved":
            return {"status": 200 if receipt["state"] == "settled" else 409,
                    "receipt": receipt}
        if not isinstance(resource_url, str) or not re.fullmatch(
            r"http://127\.0\.0\.1:\d{1,5}/sandbox/resource", resource_url
        ):
            raise SandboxReject("invalid_sandbox_resource_url")
        with self.ledger.transaction() as db:
            operation = self.ledger._row(db, tenant, receipt["id"])
            row = self._lookup(db, tenant, receipt["id"])
            if row is None:
                used = db.execute("SELECT COUNT(*) FROM sandbox_challenges").fetchone()[0]
                if used >= MAX_CHALLENGES:
                    raise SandboxReject("sandbox_challenge_limit", 409)
                created = secrets.token_hex(16)
                db.execute(
                    "INSERT INTO sandbox_challenges VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                    (created, receipt["id"], tenant, operation["request_hash"],
                     object_hash(key), secrets.token_hex(16), resource_url,
                     operation["expires"], "offered", None, None),
                )
                row = self._lookup(db, tenant, receipt["id"])
                self._event(db, row, "offered")
            if row["resource_url"] != resource_url or row["phase"] != "offered":
                raise SandboxReject("sandbox_challenge_not_available", 409)
            return {"status": 402, "required": self._required(row, operation),
                    "receipt_id": receipt["id"]}

    def _record_payment(self, principal, receipt_id, proof_hash, proof_id, required):
        tenant = self.ledger.registry.require(principal)
        with self.ledger.transaction() as db:
            operation = self.ledger._row(db, tenant, receipt_id)
            challenge = self._lookup(db, tenant, receipt_id)
            if challenge is None:
                raise SandboxReject("missing_payment_challenge", 402)
            if required != self._required(challenge, operation):
                raise SandboxReject("challenge_context_changed", 409)
            existing_proof = db.execute(
                "SELECT * FROM sandbox_proofs WHERE proof_hash=?", (proof_hash,)
            ).fetchone()
            if existing_proof:
                if (existing_proof["operation_id"] != receipt_id
                        or existing_proof["tenant"] != tenant
                        or existing_proof["proof_id"] != proof_id):
                    raise SandboxReject("payment_proof_reused", 409)
                if challenge["proof_hash"] != proof_hash:
                    raise SandboxReject("payment_proof_reused", 409)
                return self.ledger._receipt(operation), False
            reused_nonce = db.execute(
                "SELECT operation_id FROM sandbox_proofs WHERE proof_id=?", (proof_id,)
            ).fetchone()
            if reused_nonce is not None:
                raise SandboxReject("mock_payment_nonce_reused", 409)
            if operation["state"] != "reserved" or challenge["phase"] != "offered":
                raise SandboxReject("payment_challenge_already_consumed", 409)
            if self.ledger.clock() >= challenge["expires"]:
                self.ledger._transition(db, operation, "expired", "payment_challenge_expired")
                self._change(db, challenge, "expired", reason="ttl")
                # Commit expiry and release rather than rolling back a rejected proof.
                return self.ledger._receipt(self.ledger._row(db, tenant, receipt_id)), False
            try:
                if self.ledger._identity() != (
                    operation["source_hash"], operation["manifest_hash"]
                ):
                    raise MeterError("source drift")
            except (LabError, OSError):
                self.ledger._transition(db, operation, "cancelled", "source_drift")
                self._change(db, challenge, "cancelled", reason="source_drift")
                # Do not raise in this transaction: return a rejected receipt after commit.
                return self.ledger._receipt(self.ledger._row(db, tenant, receipt_id)), False
            db.execute(
                "INSERT INTO sandbox_proofs VALUES(?,?,?,?,?,?)",
                (proof_hash, proof_id, challenge["id"], receipt_id, tenant,
                 operation["request_hash"]),
            )
            self.ledger._transition(db, operation, "executing")
            self._change(db, challenge, "claimed", proof_hash=proof_hash)
            return self.ledger._receipt(self.ledger._row(db, tenant, receipt_id)), True

    def _finish(self, principal, op_id, proof_hash, status, result=None, digest=None):
        if status == "settled":
            # This fake facilitator method performs no network or money transfer.
            try:
                pseudo_transaction = self.facilitator.settle(proof_hash)
            except SandboxReject:
                status = "failed"
                pseudo_transaction = None
            if status == "settled":
                receipt = self.ledger.finish(
                    principal, op_id, "settled", result=result, digest=digest)
            else:
                receipt = self.ledger.finish(
                    principal, op_id, "failed", reason="stub_settlement_failed")
        else:
            pseudo_transaction = None
            receipt = self.ledger.finish(
                principal, op_id, "failed", reason="sandbox_execution_failed")
        with self.ledger.transaction() as db:
            challenge = self._lookup(db, self.ledger.registry.require(principal), op_id)
            if challenge["phase"] == "claimed":
                self._change(db, challenge, receipt["state"],
                             transaction=pseudo_transaction,
                             reason=receipt["failure"])
        return receipt

    def fulfill(self, principal, key, sku, params, payment, resource_url):
        """Only an accepted proof for this exact tenant+request can claim execution."""
        tenant = self.ledger.registry.require(principal)
        # Existing key can be retried, but only with the exact same SKU and body.
        prior = self.ledger.reserve(principal, key, sku, params)
        with self.ledger.transaction() as db:
            operation = self.ledger._row(db, tenant, prior["id"])
            challenge = self._lookup(db, tenant, prior["id"])
            if challenge is None:
                raise SandboxReject("payment_challenge_required", 402)
            if challenge["resource_url"] != resource_url:
                raise SandboxReject("payment_resource_mismatch", 403)
            required = self._required(challenge, operation)
        proof_hash, proof_id = self.facilitator.verify(payment, required)
        # A paid retry of identical proof and request returns the original receipt.
        receipt, acquired = self._record_payment(
            principal, prior["id"], proof_hash, proof_id, required)
        if not acquired:
            if receipt["state"] == "settled":
                return receipt
            if receipt["state"] == "executing":
                raise SandboxReject("payment_request_in_progress", 409)
            raise SandboxReject("payment_receipt_not_settled", 409)
        try:
            if self.ledger._identity() != (
                receipt["source_sha256"], receipt["manifest_sha256"]
            ):
                raise MeterError("source drift during execution")
            result, digest = self.service._dispatch(tenant, key, sku, params)
            if len(canonical_bytes(result)) > 32_768:
                raise MeterError("sandbox result exceeds limit")
        except Exception:
            return self._finish(principal, receipt["id"], proof_hash, "failed")
        return self._finish(principal, receipt["id"], proof_hash, "settled",
                            result=result, digest=digest)

    def payment_response(self, principal, operation_id):
        tenant = self.ledger.registry.require(principal)
        with self.ledger.transaction() as db:
            row = self._lookup(db, tenant, operation_id)
            if row is None or row["phase"] != "settled":
                raise SandboxReject("mock_settlement_unavailable", 409)
            return {
                "success": True, "network": NETWORK,
                "transaction": row["mock_transaction"],  # NOT an onchain TX!
                "payer": "sandbox-test-fixture",
                "sandboxOnly": True, "realFundsTransferred": False,
            }
