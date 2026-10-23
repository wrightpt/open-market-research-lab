"""Run one local x402-v2-shaped exchange with fake identities and zero real money.

Starts a literal-loopback ephemeral server, signs in-process TEST-ONLY tokens
and proof, prints sanitized state, then stops. Retains receipts under artifacts/.
"""
import argparse
import http.client
import json
import secrets
import threading

from market_lab.io import ROOT
from .ledger import PRICES
from .sandbox_http import SandboxHTTPServer
from .sandbox_identity import encode_header, decode_header


def _request(server, token, body, *, signature=None):
    conn = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=10)
    headers = {
        "Authorization": "Bearer " + token,
        "Content-Type": "application/json",
        "Origin": server.origin,
    }
    if signature:
        headers["PAYMENT-SIGNATURE"] = encode_header(signature)
    try:
        conn.request("POST", "/sandbox/resource", json.dumps(body), headers)
        response = conn.getresponse()
        result = json.loads(response.read())
        return response.status, result, response.getheader("PAYMENT-REQUIRED")
    finally:
        conn.close()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sku", choices=tuple(PRICES), default="synthetic_sample.v1")
    parser.add_argument("--tenant", choices=("demo-alpha", "demo-beta"), default="demo-alpha")
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--limit", type=int, default=2)
    args = parser.parse_args(argv)
    directory = "artifacts/x402-sandbox-demo-" + secrets.token_hex(5)
    (ROOT / "artifacts").mkdir(exist_ok=True)
    server = SandboxHTTPServer(ROOT, directory=directory)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        token = server.issuer.issue(args.tenant)
        params = {"offset": args.offset, "limit": args.limit} if (
            args.sku == "synthetic_sample.v1") else {}
        body = {"sku": args.sku, "params": params,
                "key": "demo-" + secrets.token_hex(12)}
        status, first, encoded = _request(server, token, body)
        if status != 402 or not encoded:
            raise RuntimeError("local 402 challenge was not returned")
        required = decode_header(encoded)
        mock_proof = server.exchange.facilitator.make_test_signature(required)
        status, paid, _ = _request(server, token, body, signature=mock_proof)
        if status != 200 or paid["receipt"]["state"] != "settled":
            raise RuntimeError("fake payment / development result was not accepted")
        receipt = paid["receipt"]
        print(json.dumps({
            "mode": "zero_funds_sandbox_only", "first_status": 402,
            "second_status": status, "sku": args.sku,
            "sandbox_charge_cents": receipt["charged_cents"],
            "receipt_id": receipt["id"], "evidence_sha256": receipt["evidence_sha256"],
            "replay_matched": receipt["result"].get("replay_matched"),
            "audit_verified": server.exchange.verify_audit(),
            "retained_state_directory": directory,
            "real_funds_transferred": False,
        }, indent=2))
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
