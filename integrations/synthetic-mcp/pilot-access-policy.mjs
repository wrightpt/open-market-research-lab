// PRIVATE CONNECTOR PILOT: pure authorization decision, NOT authentication.
//
// Input claims MUST come from an independently verified OAuth access token.
// This function does NOT parse JWTs, validate signatures/JWKS, check OAuth
// callbacks, issue credentials, enforce rate limits, or record audit events.
// It is intentionally NOT connected to server.mjs. Never put this between an
// external request and a tool without a production-reviewed token verifier.
export const PILOT_DATASET_ID = "synthetic-liquidity-v1";
export const PILOT_SCOPE = "research:read";
export const PILOT_TOOLS = Object.freeze([
  "list_datasets", "describe_dataset", "get_sample",
]);

function deny(reason) {
  return Object.freeze({ allowed: false, reason });
}

function nonempty(value) {
  return typeof value === "string" && value.length > 0 && value.trim() === value;
}

function exactAudience(aud, expected) {
  return aud === expected || (
    Array.isArray(aud) && aud.length > 0 &&
    aud.every(nonempty) && aud.includes(expected)
  );
}

// "claims" and "account" are trusted inputs supplied ONLY by separately
// authenticated and authorized server-side components. The caller must never
// construct either from client-provided JSON, headers, tool arguments or prompts.
export function evaluateVerifiedResearchAccess({
  claims, account, request, expectedIssuer, expectedAudience, nowEpochSeconds,
} = {}) {
  if (!nonempty(expectedIssuer) || !nonempty(expectedAudience) ||
      !Number.isSafeInteger(nowEpochSeconds) || nowEpochSeconds < 0) {
    return deny("invalid_server_policy");
  }

  if (!claims || typeof claims !== "object" ||
      !nonempty(claims.sub) || !nonempty(claims.iss) ||
      claims.iss !== expectedIssuer ||
      !exactAudience(claims.aud, expectedAudience)) {
    return deny("invalid_token_claims");
  }

  if (!Number.isSafeInteger(claims.exp) || claims.exp <= nowEpochSeconds ||
      (claims.nbf !== undefined && (
        !Number.isSafeInteger(claims.nbf) || claims.nbf > nowEpochSeconds
      ))) {
    return deny("expired_or_inactive_token");
  }

  // Only server-side verified access-token scopes count; no role or permissions
  // supplied in a client MCP payload can grant access.
  if (typeof claims.scope !== "string" ||
      !claims.scope.split(" ").filter(Boolean).includes(PILOT_SCOPE)) {
    return deny("missing_scope");
  }

  // Compare the immutable provider issuer+subject pair, not email, handle or
  // a claimed ChatGPT user ID. Account approval and revocation are server-side.
  if (!account || typeof account !== "object" ||
      !nonempty(account.internalId) ||
      account.issuer !== claims.iss || account.subject !== claims.sub ||
      account.status !== "approved" || account.revoked === true) {
    return deny("not_invited_or_revoked");
  }

  if (!request || typeof request !== "object" ||
      !PILOT_TOOLS.includes(request.tool) ||
      (request.tool !== "list_datasets" &&
       request.datasetId !== PILOT_DATASET_ID) ||
      !Array.isArray(account.datasets) ||
      !account.datasets.includes(PILOT_DATASET_ID)) {
    return deny("not_entitled");
  }

  return Object.freeze({
    allowed: true,
    accountId: account.internalId,
    datasetId: PILOT_DATASET_ID,
    scope: PILOT_SCOPE,
  });
}
