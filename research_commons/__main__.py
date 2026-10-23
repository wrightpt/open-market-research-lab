"""Run a persistent, literal-loopback synthetic evidence workspace."""

import argparse
import sys

from market_lab.io import ROOT, LabError

from .server import CommonsServer


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8787)
    parser.add_argument("--state-dir", default="artifacts/commons")
    parser.add_argument("--seed-demo", action="store_true", help="add two labeled examples once")
    args = parser.parse_args(argv)
    if not 0 <= args.port <= 65535:
        parser.error("port must be between 0 and 65535")
    try:
        with CommonsServer(ROOT, args.port, args.state_dir, args.seed_demo) as server:
            print(f"Open Research Commons: {server.origin}/commons/", flush=True)
            print("Local synthetic workspace. Ctrl-C stops the server; evidence is retained.", flush=True)
            server.serve_forever()
    except KeyboardInterrupt:
        return 0
    except (LabError, OSError) as exc:
        print(f"Cannot start local workspace: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
