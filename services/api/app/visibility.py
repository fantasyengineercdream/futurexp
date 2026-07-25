from __future__ import annotations

from typing import Any


def filter_events_for_public(
    events: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    return [
        event
        for event in events
        if event.get("visibility", {}).get("scope") == "public"
    ]


def filter_events_for_owner(
    events: list[dict[str, Any]],
    oc_id: str,
) -> list[dict[str, Any]]:
    filtered: list[dict[str, Any]] = []
    for event in events:
        visibility = event.get("visibility", {})
        scope = visibility.get("scope")
        if scope == "public":
            filtered.append(event)
        elif scope in {"owner", "actor"} and visibility.get("ocId") == oc_id:
            filtered.append(event)
    return filtered
