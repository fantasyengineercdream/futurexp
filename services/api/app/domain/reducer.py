from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from typing import Any, Iterable

from app.domain.models import CanonicalEvent, StateEffect, WorldState


def _resolve_parent(document: dict[str, Any], pointer: str) -> tuple[dict[str, Any], str]:
    parts = [part.replace("~1", "/").replace("~0", "~") for part in pointer.split("/")[1:]]
    if not parts:
        raise ValueError("effects may not replace the root state")
    current: dict[str, Any] = document
    for part in parts[:-1]:
        child = current.get(part)
        if not isinstance(child, dict):
            raise ValueError(f"invalid effect path: {pointer}")
        current = child
    return current, parts[-1]


def apply_effect(state: WorldState, effect: StateEffect) -> WorldState:
    document = deepcopy(state.model_dump(by_alias=True))
    parent, key = _resolve_parent(document, effect.path)
    current = parent.get(key)
    if current != effect.before:
        raise ValueError(
            f"effect before value mismatch at {effect.path}: "
            f"expected {effect.before!r}, got {current!r}"
        )
    if effect.op == "inc":
        if effect.by is None:
            raise ValueError("inc effect requires by")
        parent[key] = current + effect.by
    else:
        parent[key] = effect.after
    if parent[key] != effect.after:
        raise ValueError(f"effect after value mismatch at {effect.path}")
    return WorldState.model_validate(document)


def reduce_canonical_events(
    initial_state: WorldState,
    events: Iterable[CanonicalEvent],
) -> WorldState:
    state = initial_state.model_copy(deep=True)
    for event in events:
        for effect in event.effects:
            state = apply_effect(state, effect)
        state.world_version += 1
    return state


def canonical_state_checksum(state: WorldState) -> str:
    objective_state = state.model_dump(by_alias=True)
    objective_state.pop("status", None)
    objective_state.pop("tickIndex", None)
    normalized = json.dumps(
        objective_state,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(normalized).hexdigest()
