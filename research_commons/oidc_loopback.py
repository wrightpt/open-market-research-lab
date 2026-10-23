"""Optional strict OIDC JWT resource verifier for an isolated localhost Keycloak lab.

Uses a SEPARATE issuer and verifies its RS256 access-token signature via JWKS.
The tenant is mapped from a signed client identity using a *server-owned* table,
never from an untrusted tenant string or user-editable request header.

Requires the optional 'cryptography' package at runtime. The base research lab
and existing 100%-stdlib synthetic sandbox remain dependency-free.
This is an integration lab, NOT a deployable production identity service.
"""
import json
import re
import time
from urllib.parse import urlsplit
from urllib.error import HTTPError
from urllib.request import Request, build_opener, HTTPRedirectHandler, ProxyHandler

from market_lab.io import _check_tree, _unique_pairs
from .sandbox_identity import IdentityError, REQUIRED_SCOPE, _decode_piece, unb64url

MAX_DISCOVERY = 16384
MAX_JWKS = 32768
MAX_TOKEN = 8192
KID = re.compile(r"[A-Za-z0-9_.:-]{1,128}\Z")
CLIENT = re.compile(r"[A-Za-z0-9_.:-]{1,100}\Z")


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        raise IdentityError("OIDC metadata redirects are prohibited")


def _localhost_endpoint(url):
    parsed = urlsplit(url)
    if (parsed.scheme != "http" or parsed.hostname != "127.0.0.1"
            or not parsed.port or parsed.username or parsed.password
            or parsed.query or parsed.fragment or not parsed.path.startswith("/realms/")):
        raise IdentityError("OIDC integration must use a literal loopback issuer")
    return parsed


class LoopbackOIDCVerifier:
    """Separate OIDC issuer/JWKS validation; no locally minted bearer tokens."""

    def __init__(self, issuer, audience, client_tenants, *, clock=None,
                 required_scope=REQUIRED_SCOPE, timeout=2.0, cache_seconds=60):
        parsed = _localhost_endpoint(issuer)
        if issuer.endswith("/") or not parsed.path.endswith("/orc-dev"):
            raise IdentityError("unrecognized development OIDC realm")
        if not isinstance(audience, str) or not CLIENT.fullmatch(audience):
            raise IdentityError("invalid OIDC resource audience")
        if (not isinstance(client_tenants, dict) or not client_tenants
                or any(not CLIENT.fullmatch(client) or tenant not in
                       {"demo-alpha", "demo-beta"}
                       for client, tenant in client_tenants.items())):
            raise IdentityError("OIDC client-to-tenant mapping must be operator-owned")
        self.issuer = issuer
        self.audience = audience
        self.client_tenants = dict(client_tenants)
        self.required_scope = required_scope
        self.clock = clock or time.time
        self.timeout = float(timeout)
        self.cache_seconds = cache_seconds
        self._keys = {}
        self._last_fetch = 0.
        self._blocked_clients = set()
        self._revoked_jtis = set()
        metadata = self._json_get(issuer + "/.well-known/openid-configuration",
                                  MAX_DISCOVERY)
        self.jwks_uri = metadata.get("jwks_uri")
        expected = issuer + "/protocol/openid-connect/certs"
        if metadata.get("issuer") != issuer or self.jwks_uri != expected:
            raise IdentityError("OIDC discovery issuer/JWKS mismatch")
        self.refresh_keys()

    def _json_get(self, url, byte_limit):
        # Prevent redirect, arbitrary URL and secret leakage via destination.
        _localhost_endpoint(url)
        if (url != self.issuer + "/.well-known/openid-configuration"
                and url != self.issuer + "/protocol/openid-connect/certs"):
            raise IdentityError("OIDC endpoint is not allowlisted")
        # Ignore ambient HTTP_PROXY/HTTPS_PROXY; JWKS must come directly
        # from the literal-loopback issuer, never through an operator proxy.
        opener = build_opener(ProxyHandler({}), _NoRedirect)
        try:
            with opener.open(Request(url, headers={"Accept": "application/json"}),
                             timeout=self.timeout) as response:
                if response.status != 200:
                    raise IdentityError("OIDC provider is unavailable")
                raw = response.read(byte_limit + 1)
                if len(raw) > byte_limit:
                    raise IdentityError("OIDC metadata exceeds bound")
                result = json.loads(raw, object_pairs_hook=_unique_pairs)
                _check_tree(result)
                if not isinstance(result, dict):
                    raise IdentityError("invalid OIDC JSON object")
                return result
        except IdentityError:
            raise
        except HTTPError as exc:
            exc.close()
            raise IdentityError("OIDC provider lookup failed") from exc
        except Exception as exc:
            raise IdentityError("OIDC provider lookup failed") from exc

    def refresh_keys(self):
        obj = self._json_get(self.jwks_uri, MAX_JWKS)
        keys = obj.get("keys")
        if not isinstance(keys, list) or not 1 <= len(keys) <= 16:
            raise IdentityError("invalid OIDC signing key set")
        try:
            from cryptography.hazmat.primitives.asymmetric import rsa
        except ImportError as exc:
            raise IdentityError("optional cryptography dependency missing") from exc
        parsed = {}
        for jwk in keys:
            if not isinstance(jwk, dict) or jwk.get("kty") != "RSA":
                continue
            kid = jwk.get("kid")
            if (not isinstance(kid, str) or not KID.fullmatch(kid)
                    or jwk.get("use", "sig") != "sig"
                    or jwk.get("alg", "RS256") != "RS256"):
                continue
            try:
                n = int.from_bytes(unb64url(jwk["n"]), "big")
                e = int.from_bytes(unb64url(jwk["e"]), "big")
                if not 2048 <= n.bit_length() <= 4096 or e != 65537:
                    raise ValueError("nonstandard signing key")
                key = rsa.RSAPublicNumbers(e, n).public_key()
            except (ValueError, KeyError, TypeError) as exc:
                raise IdentityError("invalid RSA verification key") from exc
            if kid in parsed:
                raise IdentityError("duplicate OIDC key identifiers")
            parsed[kid] = key
        if not parsed:
            raise IdentityError("OIDC issuer has no allowed RS256 signing key")
        self._keys = parsed
        self._last_fetch = float(self.clock())

    def revoke_client(self, client):
        if client in self.client_tenants:
            self._blocked_clients.add(client)

    def revoke_token_id(self, jti):
        self._revoked_jtis.add(jti)

    def verify(self, token, registry):
        if not isinstance(token, str) or len(token) > MAX_TOKEN:
            raise IdentityError("OIDC access token is missing or oversized")
        parts = token.split(".")
        if len(parts) != 3:
            raise IdentityError("OIDC access token must be a signed JWT")
        header, claims = _decode_piece(parts[0]), _decode_piece(parts[1])
        kid = header.get("kid")
        if (header.get("alg") != "RS256" or header.get("typ") not in ("JWT", "at+jwt")
                or not isinstance(kid, str) or not KID.fullmatch(kid)):
            raise IdentityError("unsupported OIDC JWT signing algorithm")
        if float(self.clock()) - self._last_fetch > self.cache_seconds or kid not in self._keys:
            self.refresh_keys()
        key = self._keys.get(kid)
        if key is None:
            raise IdentityError("OIDC signing key is unknown")
        try:
            from cryptography.hazmat.primitives.asymmetric import padding
            from cryptography.hazmat.primitives import hashes
            from cryptography.exceptions import InvalidSignature
            sig = unb64url(parts[2])
            key.verify(sig, (parts[0] + "." + parts[1]).encode("ascii"),
                       padding.PKCS1v15(), hashes.SHA256())
        except (ValueError, TypeError, InvalidSignature) as exc:
            raise IdentityError("OIDC JWT signature verification failed") from exc
        now = int(self.clock())
        azp = claims.get("azp")
        aud = claims.get("aud")
        audiences = [aud] if isinstance(aud, str) else aud
        scopes = claims.get("scope")
        valid = (
            claims.get("iss") == self.issuer
            and isinstance(audiences, list) and self.audience in audiences
            and isinstance(azp, str) and azp in self.client_tenants
            and azp not in self._blocked_clients
            and isinstance(claims.get("sub"), str) and bool(claims["sub"])
            and claims.get("typ") == "Bearer"
            and isinstance(scopes, str) and self.required_scope in scopes.split()
            and type(claims.get("iat")) is int
            and ("nbf" not in claims or type(claims["nbf"]) is int)
            and type(claims.get("exp")) is int
            and claims["iat"] <= now + 5
            and claims.get("nbf", claims["iat"]) <= now + 5 < claims["exp"]
            and 0 < claims["exp"] - claims["iat"] <= 900
            and isinstance(claims.get("jti"), str)
            and claims["jti"] not in self._revoked_jtis
        )
        if not valid:
            raise IdentityError("OIDC token claims or tenant entitlement rejected")
        return registry.issue(self.client_tenants[azp])
