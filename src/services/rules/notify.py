"""Notification routing + predicted-alert debounce (pure decision logic).

Every alert is always displayed on the dashboard; the only routing choice is
whether it ALSO emails. So routing is a per-severity boolean (`{critical: true,
warning: true, info: false}`). Legacy string values ("email"/"both"/"display")
from earlier seeds are still understood for backward compatibility.
"""

from __future__ import annotations

from typing import Optional

# Default: critical + warning email; info is display-only.
DEFAULT_EMAIL_BY_SEVERITY = {"critical": True, "warning": True, "info": False}


def email_for_severity(severity: Optional[str], routing: Optional[dict]) -> bool:
    """Whether an alert of this severity should email (display is always on)."""
    table = routing if routing is not None else DEFAULT_EMAIL_BY_SEVERITY
    value = table.get(severity)
    if isinstance(value, bool):
        return value
    if isinstance(value, str):  # legacy 3-value action
        return value in ("email", "both")
    return DEFAULT_EMAIL_BY_SEVERITY.get(severity, False)


def predicted_email_due(cycles_seen: int, debounce_cycles: int, already_emailed: bool) -> bool:
    """A predicted alert may email once it has persisted >= debounce cycles
    (forecast-jitter filter) and has not already emailed (at-most-once)."""
    if already_emailed:
        return False
    return cycles_seen >= max(1, debounce_cycles)


def dedupe_key(
    rule_type: str,
    barn_id: Optional[str],
    feeding_location_id: Optional[str],
    origin: str,
    scope_suffix: Optional[str] = None,
) -> str:
    """Stable identity for a predicted alert across evaluation cycles.

    Deliberately excludes predicted_for and severity, so a forecast that shifts the
    crossing time or escalates the severity UPDATES the same row instead of spawning
    a new one. `scope_suffix` disambiguates same-rule alerts at different scopes."""
    parts = [rule_type, barn_id or "-", feeding_location_id or "-", origin]
    if scope_suffix:
        parts.append(scope_suffix)
    return ":".join(parts)
