from __future__ import annotations

from datetime import datetime

from jsonschema import FormatChecker


STRICT_FORMAT_CHECKER = FormatChecker()


@STRICT_FORMAT_CHECKER.checks("date-time", raises=(TypeError, ValueError))
def is_aware_iso_datetime(value: object) -> bool:
    if not isinstance(value, str):
        return False
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed.tzinfo is not None and parsed.utcoffset() is not None
