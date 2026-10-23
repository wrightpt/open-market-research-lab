"""Inspect offline, synthetic-only metering; this CLI never accepts real payment.

Selecting --tenant only selects a LOCAL TEST FIXTURE, not a verified login.
"""
import argparse
import json
import sys

from market_lab.io import ROOT, LabError

from .ledger import FixtureRegistry, OfflineLedger, PRICES
from .meter_service import OfflineResearchService


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("quote", "purchase", "balance",
                                          "receipt", "history", "cancel", "refund"))
    parser.add_argument("--tenant", choices=("demo-alpha", "demo-beta"), default="demo-alpha")
    parser.add_argument("--sku", choices=tuple(PRICES), default="synthetic_sample.v1")
    parser.add_argument("--key", help="idempotency key; needed for purchase")
    parser.add_argument("--receipt", help="receipt identifier for receipt/history/cancel/refund")
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--limit", type=int, default=2)
    parser.add_argument("--state-dir", default="artifacts/offline-metering")
    args = parser.parse_args(argv)

    if args.action == "purchase" and not args.key:
        parser.error("purchase requires --key")
    if args.action in {"receipt", "history", "cancel", "refund"} and not args.receipt:
        parser.error(f"{args.action} requires --receipt")
    registry = FixtureRegistry()
    try:
        with OfflineLedger(ROOT, registry, directory=args.state_dir) as ledger:
            principal = registry.issue(args.tenant)
            service = OfflineResearchService(ledger)
            params = {"offset": args.offset, "limit": args.limit} if (
                args.sku == "synthetic_sample.v1") else {}
            if args.action == "quote":
                data = service.quote(principal, args.sku, params)
            elif args.action == "purchase":
                data = service.purchase_fixture(principal, args.key, args.sku, params)
            elif args.action == "balance":
                data = ledger.balance(principal)
            elif args.action == "receipt":
                data = ledger.get(principal, args.receipt)
            elif args.action == "history":
                data = ledger.events(principal, args.receipt)
            elif args.action == "cancel":
                data = ledger.finish(principal, args.receipt, "cancelled",
                                     reason="operator_cancelled")
            else:
                data = ledger.finish(principal, args.receipt, "refunded",
                                     reason="offline_fixture_refund")
            print(json.dumps(data, indent=2, sort_keys=True))
    except (LabError, OSError) as exc:
        print(f"Offline demo rejected the request: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
