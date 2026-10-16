"""Toy cash/units ledger with next-open execution and explicit costs."""

import math
from datetime import datetime, timedelta

from .io import LabError


def simulate(bars, targets, execution):
    if not 2 <= len(bars) <= 1000 or len(targets) != len(bars):
        raise LabError("simulation requires 2..1000 bars and one target per bar")
    if any(type(target) is not int or target not in (0, 1) for target in targets):
        raise LabError("targets must be integer 0 (cash) or 1 (long)")
    for field, low, high in (
        ("initial_cash", 100, 1_000_000), ("fee_bps", 0, 100), ("slippage_bps", 0, 100)
    ):
        value = execution[field]
        if (
            type(value) not in (int, float) or not low <= value <= high
            or not math.isfinite(value)
        ):
            raise LabError(f"invalid execution bound: {field}")
    cash = float(execution["initial_cash"])
    units = 0.0
    fee_rate = execution["fee_bps"] / 10_000
    slip_rate = execution["slippage_bps"] / 10_000
    fills, equity = [], []

    def fill(side, reference, bar_index, decision_bar, timing):
        nonlocal cash, units
        price = reference * (1 + slip_rate if side == "buy" else 1 - slip_rate)
        quantity = cash / (price * (1 + fee_rate)) if side == "buy" else units
        notional = quantity * price
        fee = notional * fee_rate
        if side == "buy":
            units = quantity
            cash = 0.0
        else:
            cash += notional - fee
            units = 0.0
        bar_close = bars[bar_index].timestamp
        fill_time = datetime.strptime(bar_close, "%Y-%m-%dT%H:%M:%SZ")
        if timing == "next_open":
            fill_time -= timedelta(hours=1)
        fills.append({
            "side": side, "bar": bar_index,
            "timestamp": fill_time.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "bar_close_timestamp": bar_close,
            "decision_bar": decision_bar, "timing": timing,
            "reference_price": reference, "execution_price": price,
            "units": quantity, "fee": fee,
            "slippage_cost": quantity * abs(price - reference),
            "cash_after": cash, "units_after": units,
        })

    for index, bar in enumerate(bars):
        # A decision at t cannot see or trade at t+1's open until this iteration.
        target = targets[index - 1] if index > 0 else 0
        if target == 1 and units == 0:
            fill("buy", bar.open, index, index - 1, "next_open")
        elif target == 0 and units > 0:
            fill("sell", bar.open, index, index - 1, "next_open")
        mark = cash + units * bar.close
        equity.append({"bar": index, "timestamp": bar.timestamp, "equity": mark})

    # Administrative terminal liquidation, with both costs, is explicitly labeled.
    pre_exit_equity = equity[-1]["equity"]
    if units > 0:
        fill("sell", bars[-1].close, len(bars) - 1, None, "terminal_close")
        equity[-1]["equity"] = cash
    peak = execution["initial_cash"]
    max_drawdown = 0.0
    for mark in equity:
        peak = max(peak, mark["equity"])
        max_drawdown = max(max_drawdown, 1 - mark["equity"] / peak)
    # Retain the final pre-liquidation peak when measuring liquidation costs.
    peak = max(peak, pre_exit_equity)
    max_drawdown = max(max_drawdown, 1 - cash / peak)
    return {
        "summary": {
            "initial_cash": execution["initial_cash"], "final_equity": cash,
            "net_return_fraction": cash / execution["initial_cash"] - 1,
            "max_close_drawdown_fraction": max_drawdown,
            "fills": len(fills), "round_trips": sum(f["side"] == "sell" for f in fills),
            "fees_paid": sum(f["fee"] for f in fills),
            "slippage_cost": sum(f["slippage_cost"] for f in fills),
            "terminal_position_units": units,
        },
        "fills": fills, "equity_curve": equity,
    }
