"""Pure-logic tests for health_spike attribution. Run: `python test_health.py`."""

from __future__ import annotations

from health import (
    FEEDING,
    HEAT,
    UNEXPLAINED,
    attribute_cause,
    has_heat_coincidence,
    is_spike,
    spike_message,
)


def test_is_spike():
    assert is_spike(3, 3)
    assert is_spike(5, 3)
    assert not is_spike(2, 3)


def test_attribute_cause():
    assert attribute_cause(False, False) == [UNEXPLAINED]
    assert attribute_cause(True, False) == [HEAT]
    assert attribute_cause(False, True) == [FEEDING]
    assert attribute_cause(True, True) == [HEAT, FEEDING]


def test_spike_message():
    assert "reported as-is" in spike_message(4, 24, "North Barn", [UNEXPLAINED])
    msg = spike_message(7, 24, "Pen 3", [HEAT, FEEDING])
    assert "7 health events at Pen 3" in msg
    assert "coincides with heat and feeding" in msg


def test_has_heat_coincidence():
    # active heat alert short-circuits to True
    assert has_heat_coincidence(None, None, 8, heat_alert_active=True)
    # THI deviation >= delta
    assert has_heat_coincidence(84.0, 74.0, 8, heat_alert_active=False)
    # deviation below delta
    assert not has_heat_coincidence(76.0, 74.0, 8, heat_alert_active=False)
    # missing data, no active alert -> False
    assert not has_heat_coincidence(None, 74.0, 8, heat_alert_active=False)


def _run_all():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for t in tests:
        t()
        print(f"  ok: {t.__name__}")
    print(f"\nAll {len(tests)} health tests passed.")


if __name__ == "__main__":
    _run_all()
