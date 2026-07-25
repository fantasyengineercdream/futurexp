from __future__ import annotations

from app.domain.models import WorldDefinition
from app.dto import (
    OwnerSessionView,
    PassportView,
    ProofSessionView,
    WorldSessionView,
)
from app.storage import SQLiteStorage
from app.visibility import filter_events_for_owner, filter_events_for_public


def build_world_view(
    storage: SQLiteStorage,
    world: WorldDefinition,
    session_id: str,
) -> WorldSessionView:
    session = storage.get_session(session_id)
    rules = []
    for rule in world.rules:
        params = dict(rule.params)
        if rule.kind == "CONSENTED_TRANSFER_ONLY":
            params["consentRequired"] = session["consentRequired"]
        rules.append(
            {
                "ruleId": rule.rule_id,
                "kind": rule.kind,
                "label": rule.label,
                "description": rule.description,
                "enabled": rule.enabled,
                "params": params,
            }
        )
    return WorldSessionView.model_validate(
        {
            "sessionId": session_id,
            "worldId": session["worldId"],
            "status": session["status"],
            "consentRequired": session["consentRequired"],
            "lastCursor": session["lastCursor"],
            "events": filter_events_for_public(storage.get_events(session_id)),
            "world": {
                "worldId": world.world_id,
                "name": world.name,
                "aesthetic": world.aesthetic,
                "description": world.description,
                "rules": rules,
            },
        }
    )


def build_owner_view(
    storage: SQLiteStorage,
    world: WorldDefinition,
    session_id: str,
) -> OwnerSessionView:
    session = storage.get_session(session_id)
    character = world.character("oc-user")
    return OwnerSessionView.model_validate(
        {
            "sessionId": session_id,
            "worldId": session["worldId"],
            "status": session["status"],
            "consentRequired": session["consentRequired"],
            "lastCursor": session["lastCursor"],
            "checksum": session["checksum"],
            "oc": {
                "ocId": character.oc_id,
                "name": character.name,
                "role": character.role,
                "persona": character.persona,
                "publicStyle": character.public_style,
            },
            "events": filter_events_for_owner(
                storage.get_events(session_id),
                "oc-user",
            ),
        }
    )


def build_proof_view(
    storage: SQLiteStorage,
    session_id: str,
) -> ProofSessionView:
    session = storage.get_session(session_id)
    return ProofSessionView.model_validate(
        {
            "sessionId": session_id,
            "worldId": session["worldId"],
            "status": session["status"],
            "consentRequired": session["consentRequired"],
            "lastCursor": session["lastCursor"],
            "checksum": session["checksum"],
            "objectiveState": session["state"],
            "events": storage.get_events(session_id),
        }
    )


def build_passport_view(world: WorldDefinition) -> PassportView:
    character = world.character("oc-user")
    return PassportView(
        oc_id=character.oc_id,
        world_id=world.world_id,
        name=character.name,
        role=character.role,
        public_style=character.public_style,
        public_experience="曾在无限公寓公共前厅参与一次门钥匙事件。",
    )
