"""Future labels live here, separate from feature and execution inputs."""


def forward_outcome(bars, index, horizon, threshold):
    if index + horizon >= len(bars):
        return {"event": None, "forward_drawdown_fraction": None, "first_breach_bars": None}
    anchor = bars[index].close
    returns = [1 - bars[j].close / anchor for j in range(index + 1, index + horizon + 1)]
    first_breach = next((j + 1 for j, value in enumerate(returns) if value >= threshold), None)
    return {
        "event": first_breach is not None,
        "forward_drawdown_fraction": max(0.0, max(returns)),
        "first_breach_bars": first_breach,
    }


def evaluate_alerts(bars, decisions, lookback, settings):
    horizon = settings["horizon_bars"]
    counts = {"true_positive": 0, "false_positive": 0, "true_negative": 0, "false_negative": 0}
    samples, leads = [], []
    unavailable_outcomes = unavailable_features = 0
    # Consecutive sampled future intervals do not overlap. No cross-split labels.
    for index in range(lookback, len(bars), horizon):
        outcome = forward_outcome(bars, index, horizon, settings["drawdown_fraction"])
        alert = decisions[index]["alert"]
        eligible = outcome["event"] is not None and alert is not None
        samples.append({"bar": index, "alert": alert, "evaluable": eligible, **outcome})
        unavailable_outcomes += outcome["event"] is None
        unavailable_features += alert is None
        if not eligible:
            continue
        if alert and outcome["event"]:
            counts["true_positive"] += 1
            leads.append(outcome["first_breach_bars"])
        elif alert:
            counts["false_positive"] += 1
        elif outcome["event"]:
            counts["false_negative"] += 1
        else:
            counts["true_negative"] += 1
    predicted = counts["true_positive"] + counts["false_positive"]
    actual = counts["true_positive"] + counts["false_negative"]
    return {
        **counts, "evaluable_windows": sum(counts.values()),
        "unknown_outcome_windows": unavailable_outcomes,
        "unknown_feature_windows": unavailable_features,
        "precision": counts["true_positive"] / predicted if predicted else None,
        "recall": counts["true_positive"] / actual if actual else None,
        "mean_lead_bars": sum(leads) / len(leads) if leads else None,
        "samples": samples,
    }
