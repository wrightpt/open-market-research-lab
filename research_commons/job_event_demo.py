"""Finite loopback disconnect/reconnect demonstration with retained evidence."""
import argparse
import http.client
import json
import threading
import time

from market_lab.io import ROOT, load_json, repo_path, write_new
from .job_contract import LIMITS
from .job_handoff import preview_handoff
from .job_http import JobHTTPServer


def run(directory):
    if repo_path(ROOT, directory, output=True).exists():
        raise ValueError("choose a new state directory; preserve previous evidence")
    server = None
    thread = None

    def start():
        current = JobHTTPServer(directory=directory)
        running = threading.Thread(target=current.serve_forever)
        running.start()
        return current, running

    def stop():
        server.shutdown()
        thread.join(5)
        server.server_close()
        if thread.is_alive():
            raise RuntimeError("HTTP shutdown unproven")

    def call(route, payload=None, *, method="POST", credential=None):
        connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=5)
        try:
            connection.request(method, route, json.dumps(payload) if payload is not None else None,
                               {"Authorization": "Bearer " + (credential or token), "Content-Type": "application/json"})
            response = connection.getresponse()
            return response.status, json.loads(response.read())
        finally:
            connection.close()

    body = {"submission": load_json(ROOT / "submissions/baseline.json"), "split": "development",
            "resources": dict(LIMITS), "max_price_cents": 50}
    try:
        server, thread = start()
        token = server.issuer.issue("demo-alpha")
        status, job = call("/v1/jobs", {"key": "reconnect-demo-0001", "spec": body})
        if status != 202:
            raise RuntimeError("submission refused")
        # No follow-up instruction advances the worker; accepted submit wakes it.
        deadline = time.monotonic() + 15
        while True:
            _, page = call("/v1/events/read", {"consumer": "research-ui"})
            if page["events"][-1]["status"] == "succeeded":
                break
            if time.monotonic() >= deadline:
                raise RuntimeError("job completion deadline exceeded")
            time.sleep(.02)
        events = page["events"]
        _, manifest = call("/v1/jobs/" + job["id"] + "/manifest", method="GET")
        ack_body = {"consumer": "research-ui", "event_id": events[0]["event_id"]}
        _, first_ack = call("/v1/events/ack", ack_body)
        # The consumer loses the response, then reconnects after service restart.
        old_token = token
        stop()
        server = None
        server, thread = start()
        token = server.issuer.issue("demo-alpha")
        old_status, _ = call("/v1/events/read", {"consumer": "research-ui"}, credential=old_token)
        _, duplicate = call("/v1/jobs", {"key": "reconnect-demo-0001", "spec": body})
        _, retry_ack = call("/v1/events/ack", ack_body)
        _, resumed = call("/v1/events/read", {"consumer": "research-ui"})
        for event in resumed["events"]:
            status, _ = call("/v1/events/ack", {"consumer": "research-ui", "event_id": event["event_id"]})
            if status != 200:
                raise RuntimeError("acknowledgment refused")
        _, remaining = call("/v1/events/read", {"consumer": "research-ui"})
        _, after = call("/v1/jobs/" + job["id"] + "/manifest", method="GET")
        _, credits = call("/v1/credits", method="GET")
        beta = server.issuer.issue("demo-beta")
        foreign_status, _ = call("/v1/jobs/" + job["id"] + "/manifest", method="GET", credential=beta)
        proposal = preview_handoff(server.jobs, server.registry.issue("demo-alpha"),
                                   events[-1]["event_id"], "gas-city")
        checks = {"same_job": duplicate["id"] == job["id"], "same_ack": first_ack == retry_ack,
                  "same_manifest": manifest == after, "resumed_after_ack": resumed["events"] == events[1:],
                  "no_unacknowledged_events": remaining["events"] == [], "old_token_rejected": old_status == 401,
                  "cross_tenant_denied": foreign_status == 404,
                  "charged_once": credits["spent_cents"] == 50 and credits["operations"] == 1,
                  "native_dispatch_disabled": proposal["proposal"]["native_dispatch"] is False}
        if not all(checks.values()):
            raise RuntimeError("reconnect demo acceptance failed")
        summary = {"result": "PASS", "checks": checks, "job_id": job["id"],
                   "event_ids": [e["event_id"] for e in events], "first_ack": first_ack,
                   "result_manifest": manifest, "handoff_preview": proposal,
                   "evidence_level": "synthetic_engineering_only", "real_payments": False}
    finally:
        if server is not None:
            stop()
    summary["services_left_running"] = False
    write_new(ROOT, directory + "/event-demo-receipt.json", summary)
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state-dir", required=True)
    args = parser.parse_args()
    receipt = run(args.state_dir)
    print(json.dumps({"result": receipt["result"], "checks": receipt["checks"],
                      "services_left_running": False, "evidence": args.state_dir + "/event-demo-receipt.json"}))


if __name__ == "__main__":
    main()
