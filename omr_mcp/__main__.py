"""One UTF-8 JSON-RPC message per line. stdout is protocol only."""

import os
import queue
import sys
import threading

from .bounds import MAX_LINE, MAX_OUTPUT, decode, encode
from .client import Config, ResearchClient
from .protocol import Protocol, error, valid_id


def serve(source, target, client):
    events = queue.Queue(maxsize=8)
    protocol = Protocol(client)
    pending, cancelled, eof = None, False, False
    pending_cancel = None

    def read():
        while True:
            line = source.readline(MAX_LINE + 1)
            events.put(("line", line))
            if not line or len(line) > MAX_LINE or not line.endswith(b"\n"):
                return

    def write(value):
        target.write(encode(value, MAX_OUTPUT - 1, max_depth=20) + b"\n")
        target.flush()

    threading.Thread(target=read, daemon=True).start()
    while True:
        if eof and pending is None:
            return 0
        kind, line = events.get()
        if kind == "done":
            if not cancelled:
                write(line)
            pending, cancelled = None, False
            pending_cancel = None
            continue
        if not line:
            eof = True
            continue
        if len(line) > MAX_LINE or not line.endswith(b"\n"):
            write(error(None, -32600, "Line too large or missing newline; closing transport"))
            return 2
        try:
            request = decode(line, MAX_LINE)
        except (ValueError, UnicodeError, RecursionError):
            write(error(None, -32700, "Malformed or unbounded JSON"))
            continue
        if (isinstance(request, dict) and request.get("jsonrpc") == "2.0"
                and request.get("method") == "notifications/cancelled" and "id" not in request):
            params = request.get("params")
            if isinstance(params, dict) and valid_id(params.get("requestId")) and params["requestId"] == pending:
                cancelled = True
                if pending_cancel is not None:
                    pending_cancel()
            continue
        if isinstance(request, dict) and pending is not None and request.get("id") == pending:
            # Duplicate in-flight IDs are ambiguous: close, rather than emit a
            # second response with the same ID or process another HTTPS operation.
            return 2
        response = protocol.prepare(request)
        if callable(response):
            if pending is not None:
                write(error(request["id"], -32000, "One research call at a time; no automatic retry"))
                continue
            pending = request["id"]
            pending_cancel = response.cancel
            threading.Thread(target=lambda call=response: events.put(("done", call())), daemon=True).start()
        elif response is not None:
            write(response)


def main():
    if len(sys.argv) != 1:
        sys.stderr.write("Usage: python3 -m omr_mcp (configuration via environment only)\n")
        return 2
    try:
        client = ResearchClient(Config.from_env(os.environ))
    except Exception:
        sys.stderr.write("Invalid adapter configuration. Set OMR_API_URL (HTTPS origin), OMR_API_KEY, and optional OMR_CA_FILE.\n")
        return 2
    try:
        return serve(sys.stdin.buffer, sys.stdout.buffer, client)
    except (BrokenPipeError, KeyboardInterrupt):
        return 0
    except Exception:
        sys.stderr.write("Adapter stopped after a transport failure. No automatic retry.\n")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
