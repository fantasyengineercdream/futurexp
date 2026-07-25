from __future__ import annotations

from app.visibility import filter_events_for_owner, filter_events_for_public


def event(cursor: int, visibility: dict) -> dict:
    return {
        "schemaVersion": 1,
        "eventId": f"event-{cursor}",
        "cursor": cursor,
        "sessionId": "session-visibility",
        "tickIndex": 0,
        "emittedAt": "2026-07-24T00:00:00Z",
        "type": "runtime.error",
        "visibility": visibility,
        "payload": {
            "code": "TEST",
            "message": f"event {cursor}",
            "recoverable": True,
        },
    }


def test_public_filter_omits_events_before_serialization() -> None:
    events = [
        event(1, {"scope": "public"}),
        event(2, {"scope": "owner", "ocId": "oc-user"}),
        event(3, {"scope": "actor", "ocId": "oc-angel"}),
        event(4, {"scope": "tech"}),
    ]

    filtered = filter_events_for_public(events)

    assert [item["cursor"] for item in filtered] == [1]


def test_owner_filter_includes_only_public_and_matching_oc_events() -> None:
    events = [
        event(1, {"scope": "public"}),
        event(2, {"scope": "owner", "ocId": "oc-user"}),
        event(3, {"scope": "actor", "ocId": "oc-user"}),
        event(4, {"scope": "owner", "ocId": "oc-angel"}),
        event(5, {"scope": "tech"}),
    ]

    filtered = filter_events_for_owner(events, "oc-user")

    assert [item["cursor"] for item in filtered] == [1, 2, 3]
