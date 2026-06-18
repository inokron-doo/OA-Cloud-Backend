import re


def parse_feeding_activity_title(title: str) -> dict:
    if not title:
        return {
            "source_location_key": None,
            "quantity_kg": None,
        }

    pattern = (
        r"^Feeding\s*-\s*(?P<location>.*?)"
        r"(?:\s*\((?P<qty>[\d.]+)\s*kg\))?\s*$"
    )
    match = re.match(pattern, title.strip(), re.IGNORECASE)

    if not match:
        return {
            "source_location_key": None,
            "quantity_kg": None,
        }

    source_location_key = match.group("location").strip()
    qty_raw = match.group("qty")

    return {
        "source_location_key": source_location_key or None,
        "quantity_kg": float(qty_raw) if qty_raw else None,
    }
