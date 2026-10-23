"""One-shot isolated Keycloak OAuth2 client-credentials + x402 sandbox integration.

Uses a real, SEPARATE Keycloak container on random literal-loopback port.
NO public service, no cluster, no wallet, no real payments. Generates two
per-run random test client secrets, never prints them, and deletes the
temporary realm import file after stopping its owned container.

Requires docker, cryptography and localhost access. Not run in normal CI.
"""
import argparse
import json
import secrets
import shutil
import socket
import subprocess
import threading
import time
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from market_lab.io import ROOT, LabError
from research_commons.ledger import FixtureRegistry
from research_commons.oidc_loopback import LoopbackOIDCVerifier
from research_commons.sandbox_http import SandboxHTTPServer
from research_commons.sandbox_identity import decode_header, encode_header

IMAGE = "quay.io/keycloak/keycloak:26.8.1"
REALM = "orc-dev"
AUDIENCE = "orc-x402-resource"
SCOPE = "research:purchase:synthetic"
CLIENTS = {"orc-agent-a": "demo-alpha", "orc-agent-b": "demo-beta"}


def _new_local_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _realm(secrets_by_client):
    # No human users, passwords, external identity, callback, implicit grant,
    # or direct-access grant. Client credentials only for autonomous agents.
    client_scopes = [{
        "name": SCOPE, "protocol": "openid-connect",
        "attributes": {"include.in.token.scope": "true", "display.on.consent.screen": "false"},
        "protocolMappers": [{
            "name": "orc-resource-audience", "protocol": "openid-connect",
            "protocolMapper": "oidc-audience-mapper", "consentRequired": False,
            "config": {"included.client.audience": AUDIENCE,
                       "access.token.claim": "true", "id.token.claim": "false"},
        }],
    }]
    clients = [{
        "clientId": client, "enabled": True, "protocol": "openid-connect",
        "clientAuthenticatorType": "client-secret", "publicClient": False,
        "secret": secret,
        "serviceAccountsEnabled": True,
        "standardFlowEnabled": False,
        "directAccessGrantsEnabled": False,
        "implicitFlowEnabled": False,
        "fullScopeAllowed": False,
        "defaultClientScopes": [SCOPE],
    } for client, secret in secrets_by_client.items()]
    # Keycloak's audience mapper resolves an actual client, not an unknown
    # audience literal. This resource never authenticates as a buyer.
    clients.append({"clientId": AUDIENCE, "enabled": True,
                    "protocol": "openid-connect", "bearerOnly": True,
                    "publicClient": True, "serviceAccountsEnabled": False,
                    "standardFlowEnabled": False,
                    "directAccessGrantsEnabled": False})
    return {
        "realm": REALM, "enabled": True, "sslRequired": "NONE",
        "registrationAllowed": False, "resetPasswordAllowed": False,
        "loginWithEmailAllowed": False, "accessTokenLifespan": 300,
        "ssoSessionIdleTimeout": 600, "ssoSessionMaxLifespan": 600,
        "clientScopes": client_scopes,
        "clients": clients,
    }


def _docker(*argv, timeout=30):
    proc = subprocess.run(["docker", *argv], stdin=subprocess.DEVNULL,
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                          text=True, timeout=timeout, check=False)
    if proc.returncode:
        # Do not include arbitrary Docker stderr in public output; it could
        # include paths/settings from unrelated host configuration.
        raise LabError("isolated development container action failed: " + argv[0])
    return proc.stdout.strip()


def _json_request(url, body=None, timeout=3):
    data = None if body is None else urlencode(body).encode("ascii")
    request = Request(url, data=data, headers={
        "Accept": "application/json",
        "Content-Type": "application/x-www-form-urlencoded",
    })
    with urlopen(request, timeout=timeout) as response:
        if response.status != 200:
            raise LabError("development identity provider returned an error")
        raw = response.read(16_385)
        if len(raw) > 16_384:
            raise LabError("development provider response too large")
        return json.loads(raw)


def _post_sandbox(server, bearer, sku, params, key, proof=None):
    import http.client
    connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=8)
    head = {"Authorization": "Bearer " + bearer, "Content-Type": "application/json",
            "Origin": server.origin}
    if proof:
        head["PAYMENT-SIGNATURE"] = encode_header(proof)
    try:
        connection.request("POST", "/sandbox/resource",
                           json.dumps({"sku": sku, "params": params, "key": key}),
                           headers=head)
        response = connection.getresponse()
        result = json.loads(response.read(32_768))
        return response.status, result, response.getheader("PAYMENT-REQUIRED")
    finally:
        connection.close()


def run():
    port = _new_local_port()
    uid = secrets.token_hex(6)
    name = "orc-dev-keycloak-" + uid
    work = ROOT / "artifacts" / ("oidc-keycloak-integration-" + uid)
    imp = work / "import"
    imp.mkdir(parents=True)
    secrets_by_client = {client: secrets.token_urlsafe(40) for client in CLIENTS}
    (imp / (REALM + "-realm.json")).write_text(
        json.dumps(_realm(secrets_by_client)), encoding="utf-8")
    admin = secrets.token_urlsafe(40)
    container_started = False
    server = None
    thread = None
    try:
        _docker(
            "run", "-d", "--rm", "--name", name,
            "-p", f"127.0.0.1:{port}:8080",
            "--memory", "1280m", "--cpus", "2", "--pids-limit", "256",
            "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
            "-v", f"{imp}:/opt/keycloak/data/import:ro",
            "-e", "KC_BOOTSTRAP_ADMIN_USERNAME=orc-temporary-admin",
            "-e", "KC_BOOTSTRAP_ADMIN_PASSWORD=" + admin,
            IMAGE, "start-dev", "--import-realm",
            "--hostname", f"http://127.0.0.1:{port}",
            timeout=45,
        )
        container_started = True
        issuer = f"http://127.0.0.1:{port}/realms/{REALM}"
        metadata = None
        for _ in range(70):
            try:
                metadata = _json_request(issuer + "/.well-known/openid-configuration",
                                         timeout=1)
                break
            except (TimeoutError, OSError, ValueError):
                time.sleep(.5)
        if metadata is None:
            raise LabError("development Keycloak did not become ready")
        identity = LoopbackOIDCVerifier(
            issuer, AUDIENCE, CLIENTS, required_scope=SCOPE)
        tokens = {}
        for client in CLIENTS:
            reply = _json_request(
                issuer + "/protocol/openid-connect/token",
                {"grant_type": "client_credentials", "client_id": client,
                 "client_secret": secrets_by_client[client]})
            tokens[client] = reply["access_token"]
        registry = FixtureRegistry()
        server = SandboxHTTPServer(ROOT, port=0, registry=registry,
                                   directory=f"artifacts/{work.name}/ledger",
                                   identity_verifier=identity)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()

        # Diagnostic reports field shape only, never raw bearer tokens or secrets.
        # Remove/condense once issuer configuration is verified.
        from research_commons.sandbox_identity import _decode_piece
        parsed = _decode_piece(tokens['orc-agent-a'].split('.')[1])
        print(json.dumps({'oidc_claim_diagnostics': {
            'iss_ok': parsed.get('iss') == issuer,
            'aud': parsed.get('aud'), 'azp': parsed.get('azp'),
            'scope': parsed.get('scope'), 'typ': parsed.get('typ'),
            'has_iat': type(parsed.get('iat')) is int,
            'has_nbf': type(parsed.get('nbf')) is int,
            'has_exp': type(parsed.get('exp')) is int,
            'has_jti': isinstance(parsed.get('jti'), str),
        }}))
        # Proven service-account signed tokens from an actual, separately
        # running Keycloak OIDC issuer unlock two independent fixture tenants.
        receipts = {}
        for client, tenant in CLIENTS.items():
            token = tokens[client]
            signed_principal = identity.verify(token, registry)
            if registry.require(signed_principal) != tenant:
                raise LabError("provider token tenant mapping mismatch")
            key = "oidc-" + client + "-" + secrets.token_hex(5)
            status, _, payment = _post_sandbox(
                server, token, "synthetic_sample.v1", {"offset": 0, "limit": 2}, key)
            if status != 402 or not payment:
                raise LabError("OIDC authenticated request did not receive 402 challenge")
            required = decode_header(payment)
            fake_signature = server.exchange.facilitator.make_test_signature(required)
            status, received, _ = _post_sandbox(
                server, token, "synthetic_sample.v1", {"offset": 0, "limit": 2},
                key, fake_signature)
            if status != 200 or received["receipt"]["state"] != "settled":
                raise LabError("OIDC-backed sandbox purchase failed")
            receipts[client] = received["receipt"]
        identity.revoke_client("orc-agent-b")
        status, _, _ = _post_sandbox(
            server, tokens["orc-agent-b"], "synthetic_sample.v1",
            {"offset": 0, "limit": 2}, "revoked-identity-001")
        if status != 401:
            raise LabError("revoked OIDC client unexpectedly authorized")
        if not server.exchange.verify_audit():
            raise LabError("sandbox audit did not verify")
        return {
            "provider": "Keycloak " + IMAGE.rsplit(":", 1)[-1],
            "oidc_discovery_verified": metadata["issuer"] == issuer,
            "jwks_signature_verification": True,
            "client_credentials_grant": True,
            "two_tenant_isolation": True,
            "revoked_client_denied": True,
            "x402_stub_challenge_and_settlement": "402 -> 200 for both tenants",
            "receipt_count": len(receipts),
            "simulated_charges_cents": {
                client: receipt["charged_cents"] for client, receipt in receipts.items()},
            "real_funds_transferred": False,
            "data_scope": "synthetic_development_only",
        }
    finally:
        if server is not None:
            server.shutdown()
            if thread:
                thread.join(5)
            server.server_close()
        if container_started:
            try:
                _docker("stop", "--time", "2", name, timeout=20)
            except (LabError, subprocess.TimeoutExpired):
                pass
        # Delete confidential generated realm import/clients after container stop;
        # preserve the ledger and test receipts under artifacts.
        shutil.rmtree(imp, ignore_errors=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", action="store_true",
                        help="explicitly start and tear down the local test provider")
    args = parser.parse_args()
    if not args.run:
        parser.error("explicit --run required to create an isolated dev container")
    try:
        result = run()
        print(json.dumps(result, indent=2))
    except (LabError, OSError, ValueError, KeyError, subprocess.TimeoutExpired) as exc:
        print(json.dumps({"status": "blocked",
                          "reason": str(exc) if isinstance(exc, LabError)
                          else "isolated integration failed",
                          "real_funds_transferred": False}))
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
