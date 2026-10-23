"""Adversarial x402 v2-shaped HTTP sandbox tests; zero live funds and credentials."""
import copy
import http.client
import json
import sqlite3
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest import TestCase, mock

from market_lab.io import ROOT
from research_commons.sandbox_http import SandboxHTTPServer
from research_commons.sandbox_identity import (
    AUDIENCE, ISSUER, REQUIRED_SCOPE, b64url, decode_header, encode_header,
)
from research_commons.sandbox_payments import (
    NETWORK, ASSET, PAY_TO, StubFacilitator, SandboxReject,
)

SAMPLE = {"sku": "synthetic_sample.v1", "params": {"offset": 0, "limit": 2},
          "key": "unit-sample-0001"}
BACKTEST = {"sku": "synthetic_backtest.v1", "params": {}, "key": "unit-backtest-0001"}


class PaymentSandboxTests(TestCase):
    def setUp(self):
        (ROOT / "artifacts").mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(prefix="x402-http-test-", dir=ROOT / "artifacts")
        self.directory = f"artifacts/{Path(self.temp.name).name}/ledger"
        self.now = 1_000_000.0
        self._start()
        self.alpha = self.server.issuer.issue("demo-alpha")
        self.beta = self.server.issuer.issue("demo-beta")

    def _start(self):
        self.server = SandboxHTTPServer(ROOT, port=0, directory=self.directory,
                                        clock=lambda: self.now)
        self.worker = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.worker.start()

    def _stop(self):
        self.server.shutdown()
        self.worker.join(5)
        self.server.server_close()

    def tearDown(self):
        self._stop()
        self.temp.cleanup()

    def request(self, body=None, *, token=None, signature=None, route="/sandbox/resource",
                method="POST", headers=None, raw=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=6)
        token = self.alpha if token is None else token
        head = {
            "Authorization": "Bearer " + token,
            "Origin": self.server.origin,
            "Content-Type": "application/json",
        }
        if signature is not None:
            head["PAYMENT-SIGNATURE"] = signature if isinstance(signature, str) else encode_header(signature)
        head.update(headers or {})
        payload = raw if raw is not None else json.dumps(body if body is not None else SAMPLE)
        try:
            conn.request(method, route, body=payload if method == "POST" else None, headers=head)
            response = conn.getresponse()
            status = response.status
            returned_headers = dict(response.getheaders())
            body_data = response.read()
            return status, json.loads(body_data), returned_headers
        finally:
            conn.close()

    def challenge(self, body=None, *, token=None):
        status, data, headers = self.request(body, token=token)
        self.assertEqual(status, 402, data)
        required = decode_header(headers["PAYMENT-REQUIRED"])
        return required, data

    def pay(self, required, body=None, *, token=None, overrides=None):
        signed = self.server.exchange.facilitator.make_test_signature(
            required, overrides=overrides)
        return self.request(body, token=token, signature=signed)

    def test_live_loopback_headers_and_zero_funds(self):
        required, data = self.challenge()
        self.assertEqual(required["x402Version"], 2)
        self.assertEqual(required["accepts"][0]["scheme"], "exact")
        self.assertEqual(required["accepts"][0]["network"], NETWORK)
        self.assertEqual(required["accepts"][0]["asset"], ASSET)
        self.assertEqual(required["accepts"][0]["payTo"], PAY_TO)
        self.assertEqual(required["accepts"][0]["amount"], "20000")
        self.assertEqual(required["extensions"]["sandbox"]["mode"], "zero_funds_stub")
        self.assertIn("receipt_id", data)
        status, completed, headers = self.pay(required)
        self.assertEqual(status, 200, completed)
        receipt = completed["receipt"]
        self.assertEqual(receipt["charged_cents"], 2)
        self.assertEqual(receipt["state"], "settled")
        self.assertEqual(len(receipt["result"]["rows"]), 2)
        settled = decode_header(headers["PAYMENT-RESPONSE"])
        self.assertTrue(settled["sandboxOnly"])
        self.assertFalse(settled["realFundsTransferred"])
        self.assertTrue(settled["transaction"].startswith("sandbox-no-chain-"))
        self.assertEqual(self.server.ledger.balance(
            self.server.registry.issue("demo-alpha"))["spent_cents"], 2)
        self.assertTrue(self.server.exchange.verify_audit())

    def test_fixed_backtest_requires_complete_same_engine_replay(self):
        required, _ = self.challenge(BACKTEST)
        status, response, _ = self.pay(required, BACKTEST)
        self.assertEqual(status, 200, response)
        result = response["receipt"]["result"]
        self.assertEqual(result["split"], "development")
        self.assertTrue(result["replay_matched"])
        self.assertEqual(result["report_sha256"], result["replay_sha256"])
        self.assertEqual(response["receipt"]["charged_cents"], 50)

    def test_authenticated_idempotent_proof_retry_not_double_charged(self):
        required, _ = self.challenge()
        sig = self.server.exchange.facilitator.make_test_signature(required)
        with mock.patch.object(self.server.exchange.service, "_dispatch",
                               wraps=self.server.exchange.service._dispatch) as dispatch:
            first = self.request(signature=sig)
            second = self.request(signature=sig)
            self.assertEqual(dispatch.call_count, 1)
        self.assertEqual(first[0], 200)
        self.assertEqual(second[0], 200)
        self.assertEqual(first[1]["receipt"]["id"], second[1]["receipt"]["id"])
        self.assertEqual(len(self.server.exchange.ledger.events(
            self.server.registry.issue("demo-alpha"), first[1]["receipt"]["id"])), 3)
        self.assertEqual(self.server.ledger.balance(
            self.server.registry.issue("demo-alpha"))["spent_cents"], 2)

    def test_replay_proof_on_different_request_and_tenant_fails(self):
        first, _ = self.challenge()
        proof = self.server.exchange.facilitator.make_test_signature(first)
        second_body = {**SAMPLE, "key": "different-request-002"}
        second, _ = self.challenge(second_body)
        self.assertNotEqual(first["extensions"]["sandbox"]["challengeId"],
                            second["extensions"]["sandbox"]["challengeId"])
        status, _, _ = self.request(second_body, signature=proof)
        self.assertEqual(status, 400)
        status, _, _ = self.request(SAMPLE, token=self.beta, signature=proof)
        self.assertEqual(status, 402)  # beta has no such challenge, no free access
        self.assertEqual(self.server.ledger.balance(
            self.server.registry.issue("demo-beta"))["spent_cents"], 0)
        self.assertEqual(self.pay(first)[0], 200)
        # A proof already used for one request never buys the second request.
        self.assertEqual(self.request(second_body, signature=proof)[0], 400)

    def test_unsigned_tampered_or_mismatched_proof_rejected(self):
        required, _ = self.challenge()
        valid = self.server.exchange.facilitator.make_test_signature(required)
        for field, value in [
            ("amount", "10000"), ("amount", "30000"),
            ("network", "eip155:8453"), ("asset", "0x" + "1" * 40),
            ("nonce", "0" * 32), ("expiresAt", 9_999_999),
            ("tenantDigest", "0" * 64), ("requestSha256", "0" * 64),
        ]:
            with self.subTest(field=field, value=value):
                altered = self.server.exchange.facilitator.make_test_signature(
                    required, overrides={field: value})
                status, _, _ = self.request(signature=altered)
                self.assertEqual(status, 400)
        malicious = copy.deepcopy(valid)
        malicious["payload"]["sandboxSignature"] = "AA"
        self.assertEqual(self.request(signature=malicious)[0], 400)
        wrong_accepted = copy.deepcopy(valid)
        wrong_accepted["accepted"]["amount"] = "50000"
        self.assertEqual(self.request(signature=wrong_accepted)[0], 400)
        self.assertEqual(self.server.ledger.balance(
            self.server.registry.issue("demo-alpha"))["spent_cents"], 0)
        self.assertEqual(self.request(signature=valid)[0], 200)

    def test_duplicate_signed_proof_identifier_across_challenges_rejected(self):
        one, _ = self.challenge()
        first = self.server.exchange.facilitator.make_test_signature(one)
        first_id = first["payload"]["sandboxProof"]["proofId"]
        self.assertEqual(self.request(signature=first)[0], 200)
        other = {**SAMPLE, "key": "different-proof-id-key-002"}
        two, _ = self.challenge(other)
        # The stub signs this second proof legitimately, but the globally reused
        # identifier must fail even though its nonce, signature and hash differ.
        second = self.server.exchange.facilitator.make_test_signature(
            two, overrides={"proofId": first_id})
        status, message, _ = self.request(other, signature=second)
        self.assertEqual(status, 409)
        self.assertEqual(message["error"], "mock_payment_nonce_reused")
        self.assertEqual(self.server.ledger.balance(
            self.server.registry.issue("demo-alpha"))["spent_cents"], 2)
        self.assertTrue(self.server.exchange.verify_audit())

    def test_idempotency_key_binds_unchanged_request(self):
        required, _ = self.challenge()
        altered = {**SAMPLE, "params": {"offset": 0, "limit": 3}}
        status, _, _ = self.request(altered,
                                    signature=self.server.exchange.facilitator.make_test_signature(required))
        self.assertEqual(status, 409)
        self.assertEqual(self.pay(required)[0], 200)
        self.assertEqual(self.request(altered)[0], 409)

    def test_exact_issuer_audience_scope_tenant_and_signature(self):
        invalid = [
            self.server.issuer.issue("demo-alpha", overrides={"iss": "https://else.invalid"}),
            self.server.issuer.issue("demo-alpha", overrides={"aud": "wrong-resource"}),
            self.server.issuer.issue("demo-alpha", scopes=("research:read",)),
            self.server.issuer.issue("demo-alpha", overrides={"exp": int(self.now)-1}),
            self.server.issuer.issue("demo-alpha", overrides={"nbf": int(self.now)+5}),
            self.server.issuer.issue("demo-alpha", overrides={"sub": "fixture:demo-beta"}),
            self.server.issuer.issue("demo-alpha", overrides={"tenant": "not-registered"}),
        ]
        invalid.append(self.alpha[:-4] + "AAAA")
        for token in invalid:
            status, _, _ = self.request(token=token)
            self.assertEqual(status, 401)
        self.assertEqual(self.request(token="not-a-jwt")[0], 401)
        header, claims, signature = self.alpha.split(".")
        forged_none_header = b64url(json.dumps(
            {"alg": "none", "typ": "JWT", "kid": "ephemeral-test-only"}).encode())
        self.assertEqual(self.request(token=forged_none_header + "." + claims + "." + signature)[0], 401)

    def test_tenant_revocation_and_token_revocation(self):
        issued = self.server.issuer.issue("demo-alpha")
        self.server.issuer.revoke_token(issued)
        self.assertEqual(self.request(token=issued)[0], 401)
        self.server.issuer.revoke_tenant("demo-beta")
        self.assertEqual(self.request(token=self.beta)[0], 401)
        self.assertEqual(self.request(token=self.alpha)[0], 402)

    def test_cross_tenant_receipt_access_denied(self):
        required, _ = self.challenge()
        status, paid, _ = self.pay(required)
        self.assertEqual(status, 200)
        op_id = paid["receipt"]["id"]
        path = "/sandbox/receipt/" + op_id
        self.assertEqual(self.request(token=self.alpha, route=path, method="GET")[0], 200)
        self.assertEqual(self.request(token=self.beta, route=path, method="GET")[0], 404)
        self.assertEqual(self.request(token="wrong", route=path, method="GET")[0], 401)

    def test_host_origin_csrf_fetch_boundary_and_headers(self):
        self.assertEqual(self.request(headers={"Origin": "https://other.invalid"})[0], 403)
        self.assertEqual(self.request(headers={"Host": "localhost:9090"})[0], 403)
        self.assertEqual(self.request(headers={"Sec-Fetch-Site": "cross-site"})[0], 403)
        self.assertEqual(self.request(route="/sandbox/webhook")[0], 404)
        self.assertEqual(self.request(route="/x402/settle")[0], 404)
        self.assertEqual(self.request(method="GET", route="/sandbox/")[0], 404)

    def test_oversized_or_duplicate_json_cannot_reserve(self):
        self.assertEqual(self.request(raw='{"sku":"x","sku":"y","key":"k","params":{}}')[0], 400)
        self.assertEqual(self.request(raw='{"x":"' + "a" * 5000 + '"}')[0], 413)
        self.assertEqual(self.request(raw='{"sku":"synthetic_sample.v1"}')[0], 400)
        self.assertEqual(self.server.ledger.balance(
            self.server.registry.issue("demo-alpha"))["operations"], 0)

    def test_client_wrong_network_currency_amount_not_accepted(self):
        required, _ = self.challenge()
        for kind, changed in [
            ("network", "eip155:1"), ("asset", "0x" + "3" * 40),
            ("amount", "0"), ("amount", "9999999"),
        ]:
            altered = copy.deepcopy(required)
            altered["accepts"][0][kind] = changed
            signature = self.server.exchange.facilitator.make_test_signature(altered)
            with self.subTest(kind=kind):
                self.assertEqual(self.request(signature=signature)[0], 400)
        self.assertEqual(self.pay(required)[0], 200)

    def test_expired_challenge_releases_reservation(self):
        required, _ = self.challenge()
        self.assertEqual(self.server.ledger.balance(
            self.server.registry.issue("demo-alpha"))["held_cents"], 2)
        self.now += 61
        status, _, _ = self.pay(required)
        self.assertEqual(status, 409)
        receipt_id = required["extensions"]["sandbox"]["operationId"]
        principal = self.server.registry.issue("demo-alpha")
        self.assertEqual(self.server.ledger.get(principal, receipt_id)["state"], "expired")
        self.assertEqual(self.server.ledger.balance(principal)["held_cents"], 0)
        self.assertTrue(self.server.exchange.verify_audit())

    def test_stub_facilitator_outage_then_recovery(self):
        required, _ = self.challenge()
        self.server.exchange.facilitator.verify_available = False
        self.assertEqual(self.pay(required)[0], 503)
        self.assertEqual(self.server.ledger.balance(
            self.server.registry.issue("demo-alpha"))["spent_cents"], 0)
        self.server.exchange.facilitator.verify_available = True
        self.assertEqual(self.pay(required)[0], 200)

    def test_mock_settlement_outage_fails_without_charge(self):
        required, _ = self.challenge()
        self.server.exchange.facilitator.settle_available = False
        status, body, _ = self.pay(required)
        self.assertEqual(status, 409)
        self.assertEqual(body["receipt"]["state"], "failed")
        self.assertEqual(body["receipt"]["charged_cents"], 0)
        self.assertEqual(self.server.ledger.balance(
            self.server.registry.issue("demo-alpha"))["available_cents"], 200)
        self.server.exchange.facilitator.settle_available = True
        self.assertEqual(self.pay(required)[0], 409)
        self.assertTrue(self.server.exchange.verify_audit())

    def test_concurrent_proof_submit_executes_once(self):
        required, _ = self.challenge()
        sig = self.server.exchange.facilitator.make_test_signature(required)
        original = self.server.exchange.service._dispatch

        def slowed(*args):
            time.sleep(0.04)
            return original(*args)

        with mock.patch.object(self.server.exchange.service, "_dispatch", side_effect=slowed) as dispatch:
            with ThreadPoolExecutor(max_workers=2) as pool:
                replies = list(pool.map(lambda _: self.request(signature=sig), (1, 2)))
            self.assertEqual(dispatch.call_count, 1)
        self.assertIn(200, [x[0] for x in replies])
        self.assertEqual(self.server.ledger.balance(
            self.server.registry.issue("demo-alpha"))["spent_cents"], 2)

    def test_restart_reconciles_claim_no_replay_no_double_charge(self):
        required, _ = self.challenge()
        proof = self.server.exchange.facilitator.make_test_signature(required)
        principal = self.server.registry.issue("demo-alpha")
        receipt_id = required["extensions"]["sandbox"]["operationId"]
        proof_hash, proof_id = self.server.exchange.facilitator.verify(proof, required)
        claimed, acquired = self.server.exchange._record_payment(
            principal, receipt_id, proof_hash, proof_id, required)
        self.assertTrue(acquired)
        self.assertEqual(claimed["state"], "executing")
        self._stop()
        old_token = self.alpha
        self._start()
        self.alpha = self.server.issuer.issue("demo-alpha")
        self.assertEqual(self.request(token=old_token)[0], 401)
        principal = self.server.registry.issue("demo-alpha")
        after = self.server.ledger.get(principal, receipt_id)
        self.assertEqual(after["state"], "uncertain")
        self.assertEqual(after["charged_cents"], 0)
        self.assertEqual(self.server.ledger.balance(principal)["available_cents"], 200)
        self.assertEqual(self.request()[0], 409)
        self.assertTrue(self.server.exchange.verify_audit())

    def test_zero_budget_and_caller_supplied_strategy_rejected(self):
        from research_commons.ledger import FixtureRegistry, OfflineLedger, MeterError
        from research_commons.sandbox_identity import DevTokenIssuer
        from research_commons.sandbox_payments import SandboxExchange

        registry = FixtureRegistry({"demo-alpha": 1, "demo-beta": 200})
        directory = f"artifacts/{Path(self.temp.name).name}/low-budget"
        with OfflineLedger(ROOT, registry, directory=directory, clock=lambda: self.now) as ledger:
            exchange = SandboxExchange(ledger, DevTokenIssuer(now=lambda: self.now))
            with self.assertRaisesRegex(MeterError, "insufficient simulated budget"):
                exchange.challenge(registry.issue("demo-alpha"), "zero-budget-key-001",
                                   SAMPLE["sku"], SAMPLE["params"],
                                   self.server.resource_url)
            self.assertEqual(ledger.balance(registry.issue("demo-alpha"))["operations"], 0)

        attempt = {**SAMPLE, "sku": "synthetic_backtest.v1", "params": {"code": "print(1)"}}
        self.assertEqual(self.request(attempt)[0], 409)
        bad_holdout = {**SAMPLE, "params": {"offset": 0, "limit": 2, "split": "holdout"}}
        self.assertEqual(self.request(bad_holdout)[0], 409)

    def test_proof_identifier_tampering_detected_by_audit(self):
        required, _ = self.challenge()
        self.assertEqual(self.pay(required)[0], 200)
        with sqlite3.connect(self.server.ledger.db_path) as db:
            db.execute("DROP TRIGGER no_sandbox_proof_update")
            db.execute("UPDATE sandbox_proofs SET proof_id=?", ("0" * 32,))
            db.commit()
        with self.assertRaisesRegex(SandboxReject, "sandbox_proof_projection_drift"):
            self.server.exchange.verify_audit()

    def test_sandbox_audit_tampering_detected(self):
        required, _ = self.challenge()
        self.assertEqual(self.pay(required)[0], 200)
        with sqlite3.connect(self.server.ledger.db_path) as db:
            with self.assertRaises(sqlite3.DatabaseError):
                db.execute("DELETE FROM sandbox_proofs")
            db.execute("DROP TRIGGER no_sandbox_event_update")
            db.execute("UPDATE sandbox_events SET event_hash=? WHERE seq=1", ("0" * 64,))
            db.commit()
        with self.assertRaises(SandboxReject):
            self.server.exchange.verify_audit()
