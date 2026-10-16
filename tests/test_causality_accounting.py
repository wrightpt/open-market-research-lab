import unittest
from dataclasses import replace

from helpers import baseline, flat_bars
from market_lab.data import parse_bars
from market_lab.engine import simulate
from market_lab.evaluation import evaluate_alerts, forward_outcome
from market_lab.fixtures import generate_split
from market_lab.io import LabError
from market_lab.strategy import causal_features, decide


class CausalityTests(unittest.TestCase):
    def test_every_prefix_has_identical_features_and_decisions(self):
        bars = parse_bars(generate_split("development"))
        parameters = baseline()["strategy"]["parameters"]
        features = causal_features(bars, parameters["lookback_bars"])
        decisions = decide(features, parameters)
        for stop in range(1, len(bars) + 1):
            prefix = causal_features(bars[:stop], parameters["lookback_bars"])
            self.assertEqual(prefix, features[:stop])
            self.assertEqual(decide(prefix, parameters), decisions[:stop])

    def test_reference_window_excludes_current_bar(self):
        bars = flat_bars()
        bars[4] = replace(bars[4], spread_bps=30, depth_usd=250, open_interest_usd=8000)
        feature = causal_features(bars, 4)[4]
        self.assertEqual(feature.spread_ratio, 3)
        self.assertEqual(feature.depth_ratio, 0.25)
        self.assertAlmostEqual(feature.oi_change, -0.2)

    def test_missing_values_never_backfill_or_become_zero(self):
        bars = flat_bars(12)
        bars[5] = replace(bars[5], depth_usd=None)
        features = causal_features(bars, 4)
        parameters = baseline()["strategy"]["parameters"]
        decisions = decide(features, parameters)
        for index in range(5, 10):
            self.assertIsNone(features[index].depth_ratio)
            self.assertIsNone(decisions[index]["alert"])
            self.assertEqual(decisions[index]["target"], 0)
        self.assertEqual(features[10].depth_ratio, 1)

    def test_future_mutation_cannot_change_past_fills(self):
        bars = flat_bars(20)
        parameters = {**baseline()["strategy"]["parameters"], "lookback_bars": 4}
        changed = bars[:10] + [replace(b, open=50, high=50, low=40, close=40, spread_bps=100, depth_usd=1) for b in bars[10:]]
        def run(rows):
            decisions = decide(causal_features(rows, 4), parameters)
            return decisions, simulate(rows, [d["target"] for d in decisions], baseline()["execution"])
        original_decisions, original = run(bars)
        mutated_decisions, mutated = run(changed)
        self.assertEqual(original_decisions[:10], mutated_decisions[:10])
        self.assertEqual(original["equity_curve"][:10], mutated["equity_curve"][:10])
        self.assertEqual([f for f in original["fills"] if f["bar"] < 10], [f for f in mutated["fills"] if f["bar"] < 10])
        self.assertNotEqual(forward_outcome(bars, 9, 2, 0.03), forward_outcome(changed, 9, 2, 0.03))


class AccountingTests(unittest.TestCase):
    def test_next_open_timing_uses_gapped_open_not_signal_close(self):
        bars = flat_bars(4)
        bars[1] = replace(bars[1], open=200, high=200, low=200, close=200)
        bars[2] = replace(bars[2], open=150, high=150, low=150, close=150)
        execution = {**baseline()["execution"], "fee_bps": 0, "slippage_bps": 0}
        result = simulate(bars, [1, 0, 0, 0], execution)
        buy, sell = result["fills"]
        self.assertEqual((buy["decision_bar"], buy["bar"], buy["reference_price"]), (0, 1, 200))
        self.assertEqual((sell["decision_bar"], sell["bar"], sell["reference_price"]), (1, 2, 150))
        self.assertAlmostEqual(result["summary"]["final_equity"], 7500)

    def test_flat_price_round_trip_reconciles_both_costs(self):
        execution = baseline()["execution"]
        result = simulate(flat_bars(3), [1, 1, 1], execution)
        fee, slip = execution["fee_bps"] / 10000, execution["slippage_bps"] / 10000
        expected = 10000 * (1 - slip) * (1 - fee) / ((1 + slip) * (1 + fee))
        summary = result["summary"]
        self.assertAlmostEqual(summary["final_equity"], expected)
        self.assertAlmostEqual(10000 - expected, summary["fees_paid"] + summary["slippage_cost"])
        self.assertEqual(summary["round_trips"], 1)
        self.assertEqual(summary["terminal_position_units"], 0)
        self.assertEqual(result["fills"][-1]["timing"], "terminal_close")
        self.assertIsNone(result["fills"][-1]["decision_bar"])
        self.assertAlmostEqual(summary["max_close_drawdown_fraction"], 1 - expected / 10000)

    def test_last_bar_signal_cannot_trade(self):
        result = simulate(flat_bars(3), [0, 0, 1], baseline()["execution"])
        self.assertEqual(result["fills"], [])
        self.assertEqual(result["summary"]["final_equity"], 10000)

    def test_terminal_cost_uses_final_pre_exit_peak(self):
        bars = flat_bars(3)
        bars[-1] = replace(bars[-1], open=120, high=120, low=120, close=120)
        settings = {**baseline()["execution"], "fee_bps": 100, "slippage_bps": 0}
        result = simulate(bars, [1, 1, 1], settings)
        self.assertGreater(result["summary"]["final_equity"], 10000)
        self.assertAlmostEqual(result["summary"]["max_close_drawdown_fraction"], 0.01)

    def test_fill_timestamps_distinguish_open_and_terminal_close(self):
        bars = flat_bars(3)
        result = simulate(bars, [1, 1, 1], baseline()["execution"])
        buy, sell = result["fills"]
        self.assertEqual(buy["timestamp"], bars[0].timestamp)
        self.assertEqual(buy["bar_close_timestamp"], bars[1].timestamp)
        self.assertEqual(sell["timestamp"], bars[-1].timestamp)
        self.assertEqual(sell["bar_close_timestamp"], bars[-1].timestamp)

    def test_zero_cost_cash_and_long_controls(self):
        settings = {**baseline()["execution"], "fee_bps": 0, "slippage_bps": 0}
        for targets in ([0] * 6, [1] * 6):
            self.assertEqual(simulate(flat_bars(6), targets, settings)["summary"]["final_equity"], 10000)

    def test_invalid_exposure_and_costs_rejected(self):
        for targets in ([0], [0, 2], [0, -1], [0, True]):
            with self.assertRaises(LabError):
                simulate(flat_bars(2), targets, baseline()["execution"])
        for cost in (-1, float("inf"), True, 10**1000):
            with self.assertRaises(LabError):
                simulate(flat_bars(2), [0, 1], {**baseline()["execution"], "fee_bps": cost})


class EvaluationTests(unittest.TestCase):
    def test_future_outcome_boundary_and_lead_time(self):
        bars = flat_bars(6)
        bars[3] = replace(bars[3], close=95)
        result = forward_outcome(bars, 1, 2, 0.03)
        self.assertTrue(result["event"])
        self.assertEqual(result["first_breach_bars"], 2)
        self.assertIsNone(forward_outcome(bars, 4, 2, 0.03)["event"])

    def test_unknowns_excluded_and_windows_do_not_overlap(self):
        bars = flat_bars(12)
        bars[5] = replace(bars[5], close=95)
        decisions = [{"alert": False} for _ in bars]
        decisions[2] = {"alert": None}
        decisions[4] = {"alert": True}
        settings = {"horizon_bars": 2, "drawdown_fraction": 0.03}
        result = evaluate_alerts(bars, decisions, 2, settings)
        self.assertEqual([s["bar"] for s in result["samples"]], [2, 4, 6, 8, 10])
        self.assertEqual(result["unknown_outcome_windows"], 1)
        self.assertEqual(result["unknown_feature_windows"], 1)
        self.assertEqual(result["evaluable_windows"], 3)
        self.assertEqual(result["true_positive"], 1)
        self.assertEqual(result["mean_lead_bars"], 1)
        self.assertIsNone(result["samples"][-1]["event"])

    def test_empty_denominators_remain_null(self):
        bars = flat_bars(8)
        result = evaluate_alerts(bars, [{"alert": False}] * 8, 2, {"horizon_bars": 2, "drawdown_fraction": 0.03})
        self.assertIsNone(result["precision"])
        self.assertIsNone(result["recall"])
        self.assertIsNone(result["mean_lead_bars"])


if __name__ == "__main__":
    unittest.main()
