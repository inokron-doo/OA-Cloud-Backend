"""Pure-logic tests for the continuous-state rule evaluator.

Runnable with pytest OR standalone: `python src/services/rules/test_continuous.py`
(no DB or framework deps).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from continuous import (
    Sample,
    evaluate,
    heat_stress_rule,
    low_feed_rule,
    spoilage_rule,
)

T0 = datetime(2026, 6, 18, 12, 0, tzinfo=timezone.utc)


def _series(metric, values, start=T0, step_minutes=60, extra=None):
    out = []
    for i, v in enumerate(values):
        vals = {metric: v}
        if extra:
            vals.update(extra)
        out.append(Sample(t=start + timedelta(minutes=i * step_minutes), values=vals))
    return out


def test_low_feed_warning_vs_critical():
    rule = low_feed_rule(low_percent=20, critical_percent=10)
    # 12% -> warning (<=20, not <=10)
    r = evaluate(rule, [Sample(T0, {"feed_level_pct": 12.0})])
    assert r.crossed and r.severity == "warning", r
    # 8% -> critical
    r = evaluate(rule, [Sample(T0, {"feed_level_pct": 8.0})])
    assert r.crossed and r.severity == "critical", r
    # 50% -> no alert
    r = evaluate(rule, [Sample(T0, {"feed_level_pct": 50.0})])
    assert not r.crossed, r


def test_low_feed_predicted_first_crossing_time():
    rule = low_feed_rule(low_percent=20, critical_percent=10)
    # draining: crosses 20 at index 3 (15:00)
    timeline = _series("feed_level_pct", [40, 30, 25, 18, 12, 5])
    r = evaluate(rule, timeline)
    assert r.crossed and r.severity == "warning"
    assert r.sample.t == T0 + timedelta(hours=3), r.sample.t


def test_heat_sustain_warning_needs_4h():
    rule = heat_stress_rule(72, 80, warning_minutes=240, critical_minutes=360)
    # 73 for only 3 hourly samples (0..120min held) -> not yet 240min sustained
    short = _series("thi", [73, 73, 73])
    assert not evaluate(rule, short).crossed
    # 73 for 5 hourly samples -> by index 4 held=240min -> warning
    long = _series("thi", [73, 73, 73, 73, 73])
    r = evaluate(rule, long)
    assert r.crossed and r.severity == "warning"
    assert r.sample.t == T0 + timedelta(hours=4)


def test_heat_critical_beats_warning():
    rule = heat_stress_rule(72, 80, warning_minutes=240, critical_minutes=360)
    # 84 for 7 hourly samples -> critical run reaches 360min at index 6
    timeline = _series("thi", [84] * 7)
    r = evaluate(rule, timeline)
    assert r.crossed and r.severity == "critical", r
    assert r.sample.t == T0 + timedelta(hours=6)


def test_heat_run_resets_on_dip():
    rule = heat_stress_rule(72, 80, warning_minutes=240, critical_minutes=360)
    # above for 3h, dip, then above again only 2h -> never sustains 4h
    timeline = _series("thi", [75, 75, 75, 60, 75, 75])
    assert not evaluate(rule, timeline).crossed


def test_spoilage_gate_blocks_when_cool():
    rule = spoilage_rule(feed_percent=70, stale_hours=8, temp_c=25)
    # level stays 80 for 9h, but cool (20C) -> gate blocks
    cool = _series("feed_level_pct", [80] * 9, extra={"temp": 20.0})
    assert not evaluate(rule, cool).crossed
    # warm (26C) -> fires warning once 8h (480min) sustained at index 8
    warm = _series("feed_level_pct", [80] * 9, extra={"temp": 26.0})
    r = evaluate(rule, warm)
    assert r.crossed and r.severity == "warning", r
    assert r.sample.t == T0 + timedelta(hours=8)


def test_spoilage_missing_temp_does_not_block():
    rule = spoilage_rule(feed_percent=70, stale_hours=8, temp_c=25)
    no_temp = _series("feed_level_pct", [80] * 9)  # no temp metric
    r = evaluate(rule, no_temp)
    assert r.crossed and r.severity == "warning", r


def test_horizon_cuts_off_future_crossing():
    rule = low_feed_rule(low_percent=20)
    timeline = _series("feed_level_pct", [40, 30, 25, 18])  # crosses at 15:00
    horizon = T0 + timedelta(hours=2)  # only see 12:00..14:00 (>=25)
    assert not evaluate(rule, timeline, horizon_end=horizon).crossed
    assert evaluate(rule, timeline).crossed  # without horizon, it crosses


def test_empty_timeline():
    rule = low_feed_rule(low_percent=20)
    assert not evaluate(rule, []).crossed


def _run_all():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for t in tests:
        t()
        print(f"  ok: {t.__name__}")
    print(f"\nAll {len(tests)} continuous-rule tests passed.")


if __name__ == "__main__":
    _run_all()
