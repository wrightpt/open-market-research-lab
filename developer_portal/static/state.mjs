export function accountState(session) {
  if (!session || typeof session.authenticated !== "boolean") return "unavailable";
  if (!session.authenticated) return "anonymous";
  const status = session.user?.access_status;
  return ["none", "pending", "denied", "approved"].includes(status) ? status : "unavailable";
}

export function datasetRecords(value) {
  if (!Array.isArray(value?.datasets)) throw new Error("Invalid catalog");
  return value.datasets.filter(item => item && item.synthetic === true &&
    typeof item.id === "string" && typeof item.title === "string" &&
    Array.isArray(item.coverage) && Array.isArray(item.fields));
}

export function usageView(value) {
  const used = value?.usage?.requests_today, limit = value?.limits?.requests_per_day;
  if (!Number.isSafeInteger(used) || !Number.isSafeInteger(limit) || used < 0 || limit <= 0) return null;
  return {used, limit, percent: Math.min(100, 100 * used / limit)};
}

export class ApiError extends Error {
  constructor(status) { super("Portal request failed"); this.status = status; }
}

export function apiClient(fetcher, token) {
  return async function api(path, method = "GET", body) {
    if (!/^\/(session|datasets|keys|usage|access-requests|logout|keys\/[a-zA-Z0-9_-]+(?:\/rotate)?)$/.test(path)) throw new ApiError(400);
    const headers = {"Accept": "application/json"};
    if (method !== "GET") {
      if (!token()) throw new ApiError(403);
      headers["X-CSRF-Token"] = token();
      if (body !== undefined) headers["Content-Type"] = "application/json";
    }
    const response = await fetcher(`/portal/api${path}`, {
      method, headers, body: body === undefined ? undefined : JSON.stringify(body),
      credentials: "same-origin", redirect: "error", cache: "no-store",
      signal: AbortSignal.timeout(8000),
    });
    if (!response.ok) throw new ApiError(response.status);
    if (response.status === 204) return {};
    const reader = response.body.getReader();
    let size = 0, chunks = [];
    try {
      while (true) {
        const {value, done} = await reader.read();
        if (done) break;
        size += value.length;
        if (size > 1_000_000) throw new ApiError(502);
        chunks.push(value);
      }
    } finally { await reader.cancel(); }
    const bytes = new Uint8Array(size);
    let offset = 0;
    for (const chunk of chunks) { bytes.set(chunk, offset); offset += chunk.length; }
    return JSON.parse(new TextDecoder("utf-8", {fatal: true}).decode(bytes));
  };
}
