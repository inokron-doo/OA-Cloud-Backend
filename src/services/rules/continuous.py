"""Continuous-state alert rules.

A continuous-state rule is a threshold predicate over a metric sample. The SAME
evaluator runs it on the latest observed sample(s) (real-time) and on the samples
of a forecast timeline (predicted) — the only difference is which timeline is
passed in. This is the heart of the unified alert engine: "real-time" vs
"predicted" is a property of the data segment, not of the rule.

Pure logic, no DB / framework imports, so it is unit-testable in isolation.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Callable, Iterable, Optional


@dataclass(frozen=True)
class Thresholds:
    """Per-severity trigger values for a metric (None = severity not used)."""

    warning: Optional[float] = None
    critical: Optional[float] = None


@dataclass(frozen=True)
class Sustain:
    """Per-severity minutes the crossing must hold before the rule fires.

    None for a severity means "instantaneous" (a single crossing sample fires it).
    """

    warning: Optional[float] = None
    critical: Optional[float] = None


@dataclass(frozen=True)
class Gate:
    """A secondary condition checked at the crossing sample (e.g. temp >= 25)."""

    metric: str
    direction: str  # "above" | "below"
    threshold: float


@dataclass(frozen=True)
class ContinuousRule:
    rule_type: str
    metric: str  # key into Sample.values, e.g. "feed_level_pct", "thi"
    direction: str  # "below" | "above"
    thresholds: Thresholds
    sustain: Optional[Sustain] = None
    gate: Optional[Gate] = None


@dataclass(frozen=True)
class Sample:
    """A point on a state timeline. `t` is tz-aware UTC; `values` maps metric->float."""

    t: datetime
    values: dict


@dataclass(frozen=True)
class RuleResult:
    crossed: bool
    severity: Optional[str] = None
    sample: Optional[Sample] = None  # the crossing sample; predicted_for = sample.t


# Highest severity wins, so check critical before warning.
_SEVERITY_ORDER = ("critical", "warning")


def _crosses(value: Optional[float], threshold: Optional[float], direction: str) -> bool:
    if value is None or threshold is None:
        return False
    return value >= threshold if direction == "above" else value <= threshold


def _severity_of(rule: ContinuousRule, value: Optional[float]) -> Optional[str]:
    """Worst severity a single value satisfies (critical beats warning)."""
    if _crosses(value, rule.thresholds.critical, rule.direction):
        return "critical"
    if _crosses(value, rule.thresholds.warning, rule.direction):
        return "warning"
    return None


def _gate_ok(rule: ContinuousRule, sample: Sample) -> bool:
    if rule.gate is None:
        return True
    v = sample.values.get(rule.gate.metric)
    if v is None:
        # A missing gate metric does not block — matches legacy spoilage behaviour
        # (`temp_ok = latest_temp is None or latest_temp >= spoilage_temp_c`).
        return True
    return _crosses(v, rule.gate.threshold, rule.gate.direction)


def _first_sustained(
    samples: list[Sample],
    metric: str,
    threshold: float,
    direction: str,
    required_minutes: Optional[float],
    gate_ok: Callable[[Sample], bool],
) -> Optional[Sample]:
    """First sample at which a consecutive crossing-run has held >= required_minutes
    (and the gate holds at that sample). With required_minutes None, the first
    crossing sample qualifies. Any non-crossing sample resets the run."""
    run_start: Optional[datetime] = None
    for s in samples:
        if _crosses(s.values.get(metric), threshold, direction):
            if run_start is None:
                run_start = s.t
            held = (s.t - run_start).total_seconds() / 60.0
            if (required_minutes is None or held >= required_minutes) and gate_ok(s):
                return s
        else:
            run_start = None
    return None


def evaluate(
    rule: ContinuousRule,
    timeline: Iterable[Sample],
    horizon_end: Optional[datetime] = None,
) -> RuleResult:
    """Evaluate a continuous rule over a timeline.

    Observed (real-time): pass the latest observed sample(s); horizon_end=None.
    Predicted: pass forecast samples and horizon_end = now + prediction_horizon.

    Semantics differ by rule kind:
    - No sustain (e.g. low_feed): lead-time oriented — report the FIRST sample that
      crosses the least-severe threshold, at that sample's worst severity. A
      prediction's value is the earliest crossing, not a deeper low that comes later.
    - With sustain (e.g. heat_stress, spoilage_risk): escalation oriented — report the
      highest severity whose sustained, gated crossing is met anywhere in the window.
    """
    samples = sorted(
        (s for s in timeline if horizon_end is None or s.t <= horizon_end),
        key=lambda s: s.t,
    )
    if not samples:
        return RuleResult(crossed=False)

    def gate_ok(s: Sample) -> bool:
        return _gate_ok(rule, s)

    if rule.sustain is None:
        entry = (
            rule.thresholds.warning
            if rule.thresholds.warning is not None
            else rule.thresholds.critical
        )
        for s in samples:
            if _crosses(s.values.get(rule.metric), entry, rule.direction) and gate_ok(s):
                return RuleResult(crossed=True, severity=_severity_of(rule, s.values.get(rule.metric)), sample=s)
        return RuleResult(crossed=False)

    for severity in _SEVERITY_ORDER:
        threshold = getattr(rule.thresholds, severity)
        if threshold is None:
            continue
        required = getattr(rule.sustain, severity)
        hit = _first_sustained(samples, rule.metric, threshold, rule.direction, required, gate_ok)
        if hit is not None:
            return RuleResult(crossed=True, severity=severity, sample=hit)
    return RuleResult(crossed=False)


# --- Rule builders (threshold values resolved from alert_thresholds at runtime) ---

def low_feed_rule(low_percent: float, critical_percent: Optional[float] = None) -> ContinuousRule:
    return ContinuousRule(
        rule_type="low_feed",
        metric="feed_level_pct",
        direction="below",
        thresholds=Thresholds(warning=low_percent, critical=critical_percent),
    )


def heat_stress_rule(
    thi_warning: float,
    thi_critical: float,
    warning_minutes: float,
    critical_minutes: float,
) -> ContinuousRule:
    return ContinuousRule(
        rule_type="heat_stress",
        metric="thi",
        direction="above",
        thresholds=Thresholds(warning=thi_warning, critical=thi_critical),
        sustain=Sustain(warning=warning_minutes, critical=critical_minutes),
    )


def spoilage_rule(feed_percent: float, stale_hours: float, temp_c: float) -> ContinuousRule:
    return ContinuousRule(
        rule_type="spoilage_risk",
        metric="feed_level_pct",
        direction="above",
        thresholds=Thresholds(warning=feed_percent),
        sustain=Sustain(warning=stale_hours * 60.0),
        gate=Gate(metric="temp", direction="above", threshold=temp_c),
    )
