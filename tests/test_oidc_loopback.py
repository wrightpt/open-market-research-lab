"""Optional RS256/JWKS resource-server tests with an isolated OIDC metadata host.

This local issuer is a deterministic signing-test fixture; the separate
Keycloak Docker integration is run explicitly with
  python3 -m devtools.keycloak_oidc_integration --run
No real credential is used and no external network is contacted.
"""
import importlib.util
import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from research_commons.ledger import FixtureRegistry
from research_commons.oidc_loopback import LoopbackOIDCVerifier
from research_commons.sandbox_identity import IdentityError, b64url

CRYPTO = importlib.util.find_spec("cryptography") is not None
if CRYPTO:
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import padding, rsa


class MetadataServer(ThreadingHTTPServer):
    daemon_threads = True
    def __init__(self):
        self.keys = []
        self.fail = False
        super().__init__(("127.0.0.1", 0), MetadataHandler)

    @property
    def issuer(self):
        return "http://127.0.0.1:" + str(self.server_port) + "/realms/orc-dev"


class MetadataHandler(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def do_GET(self):
        if self.server.fail:
            self.send_error(503)
            return
        if self.path == "/realms/orc-dev/.well-known/openid-configuration":
            output = {"issuer": self.server.issuer,
                      "jwks_uri": self.server.issuer + "/protocol/openid-connect/certs"}
        elif self.path == "/realms/orc-dev/protocol/openid-connect/certs":
            output = {"keys": self.server.keys}
        else:
            self.send_error(404)
            return
        raw = json.dumps(output).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)


@unittest.skipUnless(CRYPTO, "optional cryptography library is not installed")
class LoopbackOIDCTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.http = MetadataServer()
        cls.clock = 1_000_000
        cls.key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        cls.jwk = cls._jwk(cls.key, "key-one")
        cls.http.keys = [cls.jwk]
        cls.thread = threading.Thread(target=cls.http.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.http.shutdown()
        cls.thread.join(5)
        cls.http.server_close()

    @classmethod
    def _jwk(cls, private, kid):
        pub = private.public_key().public_numbers()
        return {
            "kty": "RSA", "use": "sig", "alg": "RS256", "kid": kid,
            "n": b64url(pub.n.to_bytes((pub.n.bit_length()+7)//8, "big")),
            "e": b64url(pub.e.to_bytes((pub.e.bit_length()+7)//8, "big")),
        }

    def setUp(self):
        self.http.fail = False
        self.http.keys = [self.jwk]
        self.clients = {"orc-agent-a": "demo-alpha", "orc-agent-b": "demo-beta"}
        self.registry = FixtureRegistry()
        self.verifier = self.new_verifier()

    def new_verifier(self):
        return LoopbackOIDCVerifier(
            self.http.issuer, "orc-x402-resource", self.clients,
            clock=lambda: self.clock, cache_seconds=60, timeout=1,
        )

    def token(self, *, signer=None, kid="key-one", header=None, overrides=None):
        claims = {
            "iss": self.http.issuer, "aud": "orc-x402-resource",
            "azp": "orc-agent-a", "sub": "service-account-uuid-a",
            "typ": "Bearer", "scope": "openid research:purchase:synthetic",
            "iat": self.clock - 10, "exp": self.clock + 120,
            "jti": "test-token-jti-a",
        }
        if overrides:
            claims.update(overrides)
        hdr = header or {"alg": "RS256", "typ": "JWT", "kid": kid}
        head = b64url(json.dumps(hdr, sort_keys=True).encode())
        body = b64url(json.dumps(claims, sort_keys=True).encode())
        material = (head + "." + body).encode()
        key = signer or self.key
        sig = key.sign(material, padding.PKCS1v15(), hashes.SHA256())
        return head + "." + body + "." + b64url(sig)

    def test_real_rs256_jwks_and_signed_client_mapping(self):
        principal = self.verifier.verify(self.token(), self.registry)
        self.assertEqual(self.registry.require(principal), "demo-alpha")
        # Signed claim cannot self-assign a different fixture tenant.
        poisoned = self.token(overrides={"tenant": "demo-beta"})
        self.assertEqual(self.registry.require(
            self.verifier.verify(poisoned, self.registry)), "demo-alpha")

    def test_invalid_signature_alg_audience_issuer_and_scope(self):
        cases = [
            self.token(signer=rsa.generate_private_key(public_exponent=65537,key_size=2048)),
            self.token(header={"alg":"none","typ":"JWT","kid":"key-one"}),
            self.token(overrides={"aud":"elsewhere"}),
            self.token(overrides={"iss":"http://evil.invalid/realms/orc-dev"}),
            self.token(overrides={"scope":"research:read"}),
            self.token(overrides={"azp":"not-in-allowlist"}),
            self.token(overrides={"sub":""}),
            self.token(overrides={"typ":"ID"}),
        ]
        for token in cases:
            with self.subTest(token=token[:8]), self.assertRaises(IdentityError):
                self.verifier.verify(token, self.registry)

    def test_expiry_not_before_max_lifetime_and_revocation(self):
        cases = [
            {"exp":self.clock - 1},
            {"nbf":self.clock + 100},
            {"iat":self.clock + 200},
            {"exp":self.clock + 901, "iat":self.clock - 10},
            {"exp":"1000200"},
        ]
        for claims in cases:
            with self.subTest(claims=claims), self.assertRaises(IdentityError):
                self.verifier.verify(self.token(overrides=claims), self.registry)
        self.verifier.revoke_token_id("test-token-jti-a")
        with self.assertRaises(IdentityError):
            self.verifier.verify(self.token(), self.registry)
        self.verifier = self.new_verifier()
        self.verifier.revoke_client("orc-agent-a")
        with self.assertRaises(IdentityError):
            self.verifier.verify(self.token(), self.registry)

    def test_jwks_key_rotation_can_refresh_for_new_kid(self):
        self.assertEqual(self.registry.require(
            self.verifier.verify(self.token(), self.registry)), "demo-alpha")
        next_key = rsa.generate_private_key(public_exponent=65537,key_size=2048)
        self.http.keys = [self._jwk(next_key, "key-two")]
        rotated = self.token(signer=next_key, kid="key-two")
        self.assertEqual(self.registry.require(
            self.verifier.verify(rotated, self.registry)), "demo-alpha")

    def test_jwks_outage_fails_closed_when_cache_expires(self):
        self.verifier.verify(self.token(), self.registry)
        self.http.fail = True
        self.verifier._last_fetch = self.clock - 120
        with self.assertRaises(IdentityError):
            self.verifier.verify(self.token(), self.registry)

    def test_issuer_and_metadata_cannot_redirect_to_private_host(self):
        for bad in [
            "https://evil.invalid/realms/orc-dev",
            "http://localhost:9999/realms/orc-dev",
            "http://127.0.0.1:9999/realms/other",
            "http://127.0.0.1:9999/realms/orc-dev?url=http://else.invalid",
        ]:
            with self.subTest(issuer=bad), self.assertRaises(IdentityError):
                LoopbackOIDCVerifier(bad,"orc-x402-resource",self.clients)


if __name__ == "__main__":
    unittest.main()
