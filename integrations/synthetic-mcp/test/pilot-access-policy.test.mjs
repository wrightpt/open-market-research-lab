import test from "node:test";
import assert from "node:assert/strict";
import {
  evaluateVerifiedResearchAccess, PILOT_DATASET_ID, PILOT_SCOPE, PILOT_TOOLS,
} from "../pilot-access-policy.mjs";

const NOW = 1_800_000_000;
const ISSUER = "https://login.example.invalid/";
const AUDIENCE = "https://research.example.invalid/mcp";

function fixture() {
  return {
    expectedIssuer: ISSUER,
    expectedAudience: AUDIENCE,
    nowEpochSeconds: NOW,
    claims: {
      iss: ISSUER,
      sub: "provider|friend-123",
      aud: AUDIENCE,
      exp: NOW + 600,
      nbf: NOW - 30,
      scope: "openid profile " + PILOT_SCOPE,
    },
    account: {
      internalId: "researcher-0001",
      issuer: ISSUER,
      subject: "provider|friend-123",
      status: "approved",
      revoked: false,
      datasets: [PILOT_DATASET_ID],
    },
    request: { tool: "get_sample", datasetId: PILOT_DATASET_ID },
  };
}

function decision(modify) {
  const input = fixture();
  modify?.(input);
  return evaluateVerifiedResearchAccess(input);
}

test("A verified identity plus server-side invitation can read the synthetic fixture", () => {
  assert.deepEqual(decision(), {
    allowed: true,
    accountId: "researcher-0001",
    datasetId: PILOT_DATASET_ID,
    scope: PILOT_SCOPE,
  });
  assert.equal(PILOT_TOOLS.length, 3);
  assert.equal(decision(p => { p.request = { tool: "list_datasets" }; }).allowed, true);
  assert.equal(decision(p => { p.request = { tool: "describe_dataset", datasetId: PILOT_DATASET_ID }; }).allowed, true);
});

test("Missing or malformed server policy fails closed", () => {
  for (const change of [
    p => { p.expectedIssuer = ""; },
    p => { p.expectedAudience = ""; },
    p => { p.nowEpochSeconds = NaN; },
    p => { p.nowEpochSeconds = -1; },
    p => { p.nowEpochSeconds = 42.2; },
  ]) {
    assert.equal(decision(change).reason, "invalid_server_policy");
  }
});

test("Rejects forged, mismatched and absent identity claims", () => {
  for (const change of [
    p => { p.claims = null; },
    p => { p.claims.iss = "https://other.example.invalid"; },
    p => { p.claims.sub = ""; },
    p => { p.claims.aud = "https://other.example.invalid/mcp"; },
    p => { p.claims.aud = [ "https://other.example.invalid/mcp" ]; },
    p => { p.claims.aud = []; },
    p => { p.claims.aud = { value: AUDIENCE }; },
    p => { p.claims.aud = ["", AUDIENCE]; },
  ]) {
    assert.equal(decision(change).reason, "invalid_token_claims");
  }
});

test("Tokens must be temporally valid", () => {
  for (const change of [
    p => { delete p.claims.exp; },
    p => { p.claims.exp = NOW; },
    p => { p.claims.exp = NOW - 1; },
    p => { p.claims.exp = "1800000001"; },
    p => { p.claims.nbf = NOW + 1; },
    p => { p.claims.nbf = NaN; },
  ]) {
    assert.equal(decision(change).reason, "expired_or_inactive_token");
  }
});

test("Scope cannot be supplied by tool arguments, roles, or substring matches", () => {
  for (const change of [
    p => { delete p.claims.scope; },
    p => { p.claims.scope = "research:read_all"; },
    p => { p.claims.scope = ["research:read"]; },
    p => { p.claims.scope = "research:write"; },
    p => { p.claims.scope = ""; p.request.scope = PILOT_SCOPE; },
    p => { p.claims.scope = ""; p.account.role = "admin"; },
  ]) {
    assert.equal(decision(change).reason, "missing_scope");
  }
});

test("Account allowlisting uses exact provider issuer plus subject, not emails or handles", () => {
  for (const change of [
    p => { p.account = null; },
    p => { p.account.status = "pending"; },
    p => { p.account.status = "denied"; },
    p => { p.account.status = "disabled"; },
    p => { p.account.revoked = true; },
    p => { p.account.subject = "provider|friend-456"; p.account.email = "same@example.invalid"; },
    p => { p.account.issuer = "https://other.example.invalid"; },
    p => { p.account.internalId = ""; },
  ]) {
    assert.equal(decision(change).reason, "not_invited_or_revoked");
  }
});

test("Entitlements are restricted to the exact synthetic dataset and read-only tools", () => {
  for (const change of [
    p => { p.account.datasets = []; },
    p => { p.account.datasets = ["real-market"]; },
    p => { p.account.datasets = null; },
    p => { p.request.datasetId = "production-data"; },
    p => { p.request = { tool: "execute_strategy", datasetId: PILOT_DATASET_ID }; },
    p => { p.request = { tool: "kubectl", datasetId: PILOT_DATASET_ID }; },
    p => { p.request = { tool: "list_datasets", datasetId: "real-market" }; p.account.datasets = []; },
    p => { p.request = null; },
  ]) {
    assert.equal(decision(change).reason, "not_entitled");
  }
});

test("No token signature or OAuth verification is claimed here", () => {
  // Contract only: an external verified-principal provider MUST be added before
  // any public HTTP request is allowed to invoke the policy or MCP tools.
  assert.equal(evaluateVerifiedResearchAccess({}).allowed, false);
  assert.equal(typeof evaluateVerifiedResearchAccess, "function");
});
