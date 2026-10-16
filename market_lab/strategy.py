"""Causal features and one bounded, built-in long/cash rule."""

from dataclasses import asdict, dataclass
from statistics import median


@dataclass(frozen=True)
class Features:
    spread_ratio: float | None = None
    depth_ratio: float | None = None
    oi_change: float | None = None


def causal_features(bars, lookback):
    """At close t, use current values and references strictly before t.

    No centered windows, backfill, full-sample normalization, or future labels.
    A missing required observation invalidates the relevant feature.
    """
    result = []
    for index, current in enumerate(bars):
        if index < lookback:
            result.append(Features())
            continue
        trailing = bars[index - lookback:index]

        def ratio(field):
            values = [getattr(bar, field) for bar in trailing]
            value = getattr(current, field)
            if value is None or any(v is None for v in values):
                return None
            reference = median(values)
            return value / reference if reference > 0 else None

        oi_values = [bar.open_interest_usd for bar in trailing] + [current.open_interest_usd]
        oi_change = None
        if all(value is not None and value > 0 for value in oi_values):
            oi_change = oi_values[-1] / oi_values[0] - 1
        result.append(Features(ratio("spread_bps"), ratio("depth_usd"), oi_change))
    return result


def decide(features, parameters):
    result = []
    for index, feature in enumerate(features):
        values = asdict(feature)
        if any(value is None for value in values.values()):
            score, alert, target = None, None, 0
            reason = "warmup_or_missing"
        else:
            score = sum((
                feature.spread_ratio >= parameters["spread_ratio_min"],
                feature.depth_ratio <= parameters["depth_ratio_max"],
                feature.oi_change <= -parameters["oi_drop_min"],
            ))
            alert = score >= parameters["min_signals"]
            target = 0 if alert else 1
            reason = "deterioration" if alert else "no_alert"
        result.append({
            "bar": index, "features": values, "score": score, "alert": alert,
            "target": target, "reason": reason,
        })
    return result
