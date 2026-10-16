import test from "node:test";
import assert from "node:assert/strict";
import {accountState, datasetRecords, usageView, apiClient} from "../static/state.mjs";

test("account states fail closed and distinguish authentication from approval", () => {
  assert.equal(accountState(null), "unavailable");
  assert.equal(accountState({authenticated: false}), "anonymous");
  for (const status of ["none", "pending", "denied", "approved"]) assert.equal(accountState({authenticated: true, user: {access_status: status}}), status);
  assert.equal(accountState({authenticated: true, user: {access_status: "admin"}}), "unavailable");
});
test("catalog admits only declared synthetic records", () => {
  const record = {id: "fixture", title: "Fixture", synthetic: true, fields: [], coverage: []};
  assert.equal(datasetRecords({datasets: [record, {...record, synthetic: false}, null]}).length, 1);
  assert.throws(() => datasetRecords({}));
});
test("usage never invents missing or invalid quota", () => {
  for (const value of [{}, {usage: {requests_today: -1}}, {limits: {requests_per_day: 0}}]) assert.equal(usageView(value), null);
  assert.deepEqual(usageView({limits: {requests_per_day: 10}, usage: {requests_today: 15}}), {used: 15, limit: 10, percent: 100});
});
test("mutation includes CSRF and fixed same-origin redirect policy", async () => {
  let captured;
  const api = apiClient(async (...args) => { captured = args; return Response.json({keys: []}); }, () => "mock-csrf");
  await api("/keys", "POST", {name: "test"});
  assert.equal(captured[0], "/portal/api/keys");
  assert.equal(captured[1].headers["X-CSRF-Token"], "mock-csrf");
  assert.equal(captured[1].credentials, "same-origin");
  assert.equal(captured[1].redirect, "error");
  assert.equal(captured[1].cache, "no-store");
});
test("no CSRF means no mutation request", async () => {
  const api = apiClient(() => { throw new Error("must not fetch"); }, () => null);
  await assert.rejects(api("/keys", "POST", {}), {status: 403});
});
test("no arbitrary API path or absolute URL", async () => {
  const api = apiClient(() => { throw new Error("must not fetch"); }, () => "mock");
  for (const path of ["https://invalid.example", "/../keys", "/keys/x?token=hidden", "/keys/x/../../logout"]) await assert.rejects(api(path), {status: 400});
});
test("HTTP denial and failure never expose server bodies", async () => {
  for (const status of [401, 403, 429, 503]) {
    const api = apiClient(async () => new Response("sensitive response", {status}), () => "mock");
    await assert.rejects(api("/keys"), error => error.status === status && !error.message.includes("sensitive"));
  }
});
test("malformed and oversized responses fail without silently succeeding", async () => {
  const invalid = apiClient(async () => new Response("bad json"), () => "mock");
  await assert.rejects(invalid("/session"));
  const large = apiClient(async () => new Response("x".repeat(1_000_001)), () => "mock");
  await assert.rejects(large("/session"), {status: 502});
});
