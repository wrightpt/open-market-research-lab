"""Ephemeral test-token issuer for the zero-funds x402 sandbox.

This is NOT an OAuth/OIDC provider, JWKS consumer, GitHub login, or reusable
production authentication component. Tokens never come from a network route.
"""
import base64
import hashlib
import hmac
import json
import re
import secrets
import time

from market_lab.io import LabError, canonical_bytes, _unique_pairs, _check_tree


ISSUER = "https://issuer.sandbox.invalid"
AUDIENCE = "open-research-commons-x402-sandbox"
REQUIRED_SCOPE = "research:purchase:synthetic"
TENANT_ID = re.compile(r"[a-z][a-z0-9-]{2,39}\Z")
JTI = re.compile(r"[a-f0-9]{32}\Z")
MAX_TOKEN_BYTES = 2048
MAX_LIFETIME_SECONDS = 300


class IdentityError(LabError):
    """The signed *development fixture* identity is invalid or unauthorized."""


def b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def unb64url(value: str) -> bytes:
    if not isinstance(value, str) or len(value) > MAX_TOKEN_BYTES:
        raise IdentityError("invalid development identity")
    if not re.fullmatch(r"[A-Za-z0-9_-]+", value):
        raise IdentityError("invalid development identity")
    try:
        data = base64.b64decode(value + "=" * (-len(value) % 4), altchars=b"-_", validate=True)
    except (ValueError, base64.binascii.Error) as exc:
        raise IdentityError("invalid development identity") from exc
    if b64url(data) != value:
        raise IdentityError("invalid development identity")
    return data


def _decode_piece(piece):
    try:
        result = json.loads(unb64url(piece), object_pairs_hook=_unique_pairs)
        _check_tree(result)
    except (ValueError, UnicodeError, RecursionError, TypeError) as exc:
        raise IdentityError("malformed development identity") from exc
    if type(result) is not dict:
        raise IdentityError("malformed development identity")
    return result


class DevTokenIssuer:
    """Creates narrow, signed fake tokens only for trusted in-process tests."""

    def __init__(self, *, now=None):
        self._secret = secrets.token_bytes(32)
        self._revoked_tenants = set()
        self._revoked_tokens = set()
        self._now = now or time.time

    def issue(self, tenant, *, scopes=(REQUIRED_SCOPE,), overrides=None, lifetime=120):
        if not isinstance(tenant, str) or not TENANT_ID.fullmatch(tenant):
            raise IdentityError("invalid fixture tenant")
        if type(lifetime) is not int or not 1 <= lifetime <= MAX_LIFETIME_SECONDS:
            raise IdentityError("invalid fixture token lifetime")
        now = int(self._now())
        payload = {
            "iss": ISSUER, "aud": AUDIENCE, "sub": "fixture:" + tenant,
            "tenant": tenant, "scope": list(scopes), "iat": now,
            "nbf": now, "exp": now + lifetime, "jti": secrets.token_hex(16),
        }
        if overrides:
            payload.update(overrides)
        header = {"alg": "HS256", "typ": "JWT", "kid": "ephemeral-test-only"}
        signing = b64url(canonical_bytes(header)) + "." + b64url(canonical_bytes(payload))
        mac = hmac.new(self._secret, signing.encode("ascii"), hashlib.sha256).digest()
        return signing + "." + b64url(mac)

    def revoke_tenant(self, tenant):
        self._revoked_tenants.add(tenant)

    def revoke_token(self, token):
        parts = token.split(".")
        if len(parts) == 3:
            payload = _decode_piece(parts[1])
            if type(payload.get("jti")) is str:
                self._revoked_tokens.add(payload["jti"])

    def verify(self, token, registry):
        if type(token) is not str or len(token) > MAX_TOKEN_BYTES:
            raise IdentityError("development bearer token required")
        parts = token.split(".")
        if len(parts) != 3:
            raise IdentityError("invalid development identity")
        header, claims = _decode_piece(parts[0]), _decode_piece(parts[1])
        if header != {"alg": "HS256", "typ": "JWT", "kid": "ephemeral-test-only"}:
            raise IdentityError("unsupported development identity algorithm")
        signing = (parts[0] + "." + parts[1]).encode("ascii")
        expected = hmac.new(self._secret, signing, hashlib.sha256).digest()
        actual = unb64url(parts[2])
        if not hmac.compare_digest(actual, expected):
            raise IdentityError("invalid development identity signature")
        now = int(self._now())
        if (claims.get("iss") != ISSUER or claims.get("aud") != AUDIENCE
                or type(claims.get("iat")) is not int
                or type(claims.get("nbf")) is not int
                or type(claims.get("exp")) is not int
                or not claims["iat"] <= now or not claims["nbf"] <= now < claims["exp"]
                or not 0 < claims["exp"] - claims["iat"] <= MAX_LIFETIME_SECONDS
                or not isinstance(claims.get("tenant"), str)
                or not TENANT_ID.fullmatch(claims["tenant"])
                or claims.get("sub") != "fixture:" + claims["tenant"]
                or type(claims.get("scope")) is not list
                or REQUIRED_SCOPE not in claims["scope"]
                or any(type(scope) is not str or len(scope) > 64
                       for scope in claims["scope"])
                or type(claims.get("jti")) is not str
                or not JTI.fullmatch(claims["jti"])
                or claims["jti"] in self._revoked_tokens
                or claims["tenant"] in self._revoked_tenants):
            raise IdentityError("development identity not authorized")
        return registry.issue(claims["tenant"])


def encode_header(payload: dict) -> str:
    """x402 v2 transport encoding: base64(JSON), not JWT base64url."""
    if type(payload) is not dict:
        raise IdentityError("header must be a JSON object")
    encoded = base64.b64encode(canonical_bytes(payload)).decode("ascii")
    if len(encoded) > 8192:
        raise IdentityError("sandbox header too large")
    return encoded


def decode_header(encoded: str) -> dict:
    if type(encoded) is not str or not 0 < len(encoded) <= 8192:
        raise IdentityError("invalid sandbox payment header")
    try:
        raw = base64.b64decode(encoded, validate=True)
        if len(raw) > 6144 or base64.b64encode(raw).decode("ascii") != encoded:
            raise IdentityError("invalid sandbox payment header")
        result = json.loads(raw, object_pairs_hook=_unique_pairs)
        _check_tree(result)
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise IdentityError("invalid sandbox payment header") from exc
    if type(result) is not dict:
        raise IdentityError("invalid sandbox payment header")
    return result
