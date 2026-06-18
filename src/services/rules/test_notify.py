"""Pure-logic tests for notification routing + debounce + dedupe key.

Run: `python src/services/rules/test_notify.py` (or via pytest).
"""

from __future__ import annotations

from notify import (
    dedupe_key,
    email_for_severity,
    predicted_email_due,
)

ROUTING = {"critical": True, "warning": True, "info": False}


def test_email_for_severity_bool():
    assert email_for_severity("critical", ROUTING) is True
    assert email_for_severity("warning", ROUTING) is True
    assert email_for_severity("info", ROUTING) is False
    # unknown severity -> default table
    assert email_for_severity("bogus", ROUTING) is False


def test_email_for_severity_defaults_and_legacy():
    # None routing -> sensible defaults (critical+warning email, info not)
    assert email_for_severity("critical", None) is True
    assert email_for_severity("info", None) is False
    # legacy 3-value strings still understood
    legacy = {"critical": "both", "warning": "email", "info": "display"}
    assert email_for_severity("critical", legacy) is True
    assert email_for_severity("warning", legacy) is True
    assert email_for_severity("info", legacy) is False


def test_predicted_email_due():
    # below debounce -> not yet
    assert predicted_email_due(1, 3, already_emailed=False) is False
    assert predicted_email_due(2, 3, already_emailed=False) is False
    # reaches debounce -> due
    assert predicted_email_due(3, 3, already_emailed=False) is True
    assert predicted_email_due(9, 3, already_emailed=False) is True
    # at-most-once
    assert predicted_email_due(9, 3, already_emailed=True) is False


def test_dedupe_key_stability_and_scope():
    assert dedupe_key("low_feed", "barn-1", "loc-9", "predicted") == "low_feed:barn-1:loc-9:predicted"
    assert dedupe_key("heat_stress", "barn-1", None, "predicted") == "heat_stress:barn-1:-:predicted"
    kb = dedupe_key("health_spike", "barn-1", None, "observed", scope_suffix="barn")
    kl = dedupe_key("health_spike", "barn-1", "loc-9", "observed", scope_suffix="location")
    assert kb != kl and kb.endswith(":barn") and kl.endswith(":location")


def _run_all():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for t in tests:
        t()
        print(f"  ok: {t.__name__}")
    print(f"\nAll {len(tests)} notify tests passed.")


if __name__ == "__main__":
    _run_all()
