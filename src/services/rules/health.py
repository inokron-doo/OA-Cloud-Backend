"""Health-event spike: rate threshold + suspected-cause attribution.

Pure logic for the redesigned MooHero alerting. Instead of one alert per health
event (noise) plus two overlapping spike alerts, there is a SINGLE rate-based
`health_spike` rule: fire when >= count events occur in a window at a scope, then
attribute a suspected cause (heat / feeding / unexplained) as a field on that one
alert. The DB-bound parts (counting events, detecting heat/feeding coincidence)
live in meta_rules.py; this module holds the testable decision + message core.
"""

from __future__ import annotations

from typing import List, Optional

HEAT = "heat"
FEEDING = "feeding"
UNEXPLAINED = "unexplained"


def is_spike(event_count: int, spike_count: int) -> bool:
    return event_count >= spike_count


def attribute_cause(has_heat: bool, has_feeding: bool) -> List[str]:
    """Suspected cause(s) for a spike. Neither coincidence -> reported as-is."""
    causes: List[str] = []
    if has_heat:
        causes.append(HEAT)
    if has_feeding:
        causes.append(FEEDING)
    return causes or [UNEXPLAINED]


def spike_message(
    event_count: int,
    window_hours: int,
    scope_label: str,
    causes: List[str],
) -> str:
    head = (
        f"{event_count} health events at {scope_label} in the last {window_hours}h"
    )
    if causes == [UNEXPLAINED]:
        return f"{head} — no weather or feeding correlation; reported as-is."
    nice = " and ".join(causes)
    return f"{head} — coincides with {nice}."


def has_heat_coincidence(
    current_thi: Optional[float],
    avg_thi: Optional[float],
    thi_delta: float,
    heat_alert_active: bool,
) -> bool:
    """Heat is a suspected cause if a heat_stress alert is active, or current THI
    deviates from the recent average by at least `thi_delta`."""
    if heat_alert_active:
        return True
    if current_thi is None or avg_thi is None:
        return False
    return abs(current_thi - avg_thi) >= thi_delta
