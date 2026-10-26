"""One finite HTTP demonstration, retained evidence, and complete shutdown."""
import argparse
import http.client
import json
from pathlib import Path
import threading
import time

from market_lab.io import ROOT, load_json, repo_path, write_new
from .job_contract import LIMITS
from .job_http import JobHTTPServer


def run(directory):
    if repo_path(ROOT, directory, output=True).exists():
        raise ValueError("choose a new state directory; preserve previous evidence")
    server = JobHTTPServer(directory=directory, start_worker=False)
    thread = threading.Thread(target=server.serve_forever)
    thread.start()
    tokens = {name: server.issuer.issue(name) for name in ("demo-alpha", "demo-beta")}

    def call(tenant, method, route, payload=None):
        connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=5)
        connection.request(method, route, json.dumps(payload) if payload is not None else None,
                           {"Authorization": "Bearer " + tokens[tenant], "Content-Type": "application/json"})
        response = connection.getresponse()
        result = response.status, json.loads(response.read())
        connection.close()
        return result

    body = {"submission": load_json(ROOT / "submissions/baseline.json"), "split": "development",
            "resources": dict(LIMITS), "max_price_cents": 50}
    try:
        _, cancelled = call("demo-alpha", "POST", "/v1/jobs", {"key": "cancelled-demo-0001", "spec": body})
        call("demo-alpha", "POST", "/v1/jobs/" + cancelled["id"] + "/cancel", {})
        jobs = {}
        for tenant in tokens:
            status, receipt = call(tenant, "POST", "/v1/jobs", {"key": "same-tenant-key", "spec": body})
            if status != 202:
                raise RuntimeError("demo submission refused")
            jobs[tenant] = receipt["id"]
        _, duplicate = call("demo-alpha", "POST", "/v1/jobs", {"key": "same-tenant-key", "spec": body})
        server.jobs.start()
        deadline = time.monotonic() + 25
        results = {}
        for tenant, job_id in jobs.items():
            while True:
                _, receipt = call(tenant, "GET", "/v1/jobs/" + job_id)
                if receipt["status"] not in {"queued", "running"}:
                    results[tenant] = receipt
                    break
                if time.monotonic() >= deadline:
                    raise RuntimeError("demo deadline exceeded")
                time.sleep(.02)
        cross_status, _ = call("demo-beta", "GET", "/v1/jobs/" + jobs["demo-alpha"] + "/result")
        summary = {
            "evidence_level": "synthetic_engineering_only", "real_payments": False,
            "trigger": "accepted HTTP submission wakes local controller",
            "duplicate_same_job": duplicate["id"] == jobs["demo-alpha"],
            "cross_tenant_result_http_status": cross_status,
            "cancelled": call("demo-alpha", "GET", "/v1/jobs/" + cancelled["id"])[1],
            "jobs": results,
            "credits": {tenant: call(tenant, "GET", "/v1/credits")[1] for tenant in tokens},
        }
        if (cross_status != 404 or not summary["duplicate_same_job"]
                or any(r["status"] != "succeeded" for r in results.values())):
            raise RuntimeError("demo acceptance failed")
        write_new(ROOT, directory + "/demo-receipt.json", summary)
        return summary
    finally:
        server.shutdown()
        thread.join(5)
        server.server_close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state-dir", required=True)
    args = parser.parse_args()
    result = run(args.state_dir)
    print(json.dumps({"result": "PASS", "tenants": len(result["jobs"]),
                      "duplicate_same_job": result["duplicate_same_job"],
                      "cross_tenant_result_http_status": result["cross_tenant_result_http_status"],
                      "evidence": args.state_dir + "/demo-receipt.json",
                      "services_left_running": False}))


if __name__ == "__main__":
    main()
