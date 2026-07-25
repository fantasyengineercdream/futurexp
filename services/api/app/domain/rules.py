from __future__ import annotations

import hashlib
import hmac
import json
import secrets

from pydantic import BaseModel

from app.domain.models import (
    CanonicalEvent,
    CharacterProposal,
    PerceptualAtom,
    Resolution,
    ResolutionReceipt,
    RuleDecision,
    StateEffect,
    DmProposal,
    UtteranceProposal,
    WorldDefinition,
    WorldState,
)
from app.errors import DomainInvariantError


class RuleKernel:
    """The only component that turns proposals into canonical effects."""

    def __init__(
        self,
        world: WorldDefinition,
        *,
        authority: "ResolutionAuthority | None" = None,
    ) -> None:
        self.world = world
        self._authority = authority or ResolutionAuthority()

    def resolve_character(
        self,
        proposal: CharacterProposal,
        state: WorldState,
        *,
        sequence: int,
        decision_id: str,
        canonical_event_id: str,
    ) -> Resolution:
        action = proposal.action
        if action.kind == "ACCUSE":
            return self._seal(
                proposal,
                state,
                self._invalid(
                    proposal.proposal_id,
                    decision_id,
                    "USE_UTTERANCE_PROPOSAL",
                ),
            )
        if action.kind == "MOVE":
            return self._seal(
                proposal,
                state,
                self._resolve_move(
                    proposal,
                    state,
                    sequence,
                    decision_id,
                    canonical_event_id,
                ),
            )
        if action.kind == "WAIT":
            return self._seal(
                proposal,
                state,
                self._resolve_wait(
                    proposal,
                    state,
                    sequence,
                    decision_id,
                    canonical_event_id,
                ),
            )
        world_object = state.objects.get(action.object_id)
        if world_object is None:
            return self._seal(
                proposal,
                state,
                self._invalid(
                    proposal.proposal_id,
                    decision_id,
                    "OBJECT_NOT_FOUND",
                ),
            )

        if action.kind == "TAKE":
            return self._seal(
                proposal,
                state,
                self._resolve_take(
                    proposal,
                    state,
                    sequence,
                    decision_id,
                    canonical_event_id,
                ),
            )
        if action.kind == "GIVE":
            return self._seal(
                proposal,
                state,
                self._resolve_give(
                    proposal,
                    state,
                    sequence,
                    decision_id,
                    canonical_event_id,
                ),
            )
        raise DomainInvariantError(f"unsupported character action: {action.kind}")

    def _resolve_wait(
        self,
        proposal: CharacterProposal,
        state: WorldState,
        sequence: int,
        decision_id: str,
        canonical_event_id: str,
    ) -> Resolution:
        try:
            actor = self.world.character(proposal.actor_id)
        except StopIteration:
            return self._invalid(
                proposal.proposal_id,
                decision_id,
                "ACTOR_NOT_FOUND",
            )
        decision = RuleDecision(
            decision_id=decision_id,
            proposal_id=proposal.proposal_id,
            verdict="resolved",
            outcome="success",
            matched_rule_ids=[],
            reason_codes=["ACTOR_CHOSE_TO_WAIT"],
        )
        event = CanonicalEvent(
            canonical_event_id=canonical_event_id,
            sequence=sequence,
            kind="action.resolved",
            actor_id=proposal.actor_id,
            decision_id=decision_id,
            fact_codes=["actor.waited"],
            effects=[],
            perceptual_atoms=[
                PerceptualAtom(
                    atom_id=f"{canonical_event_id}-present",
                    code="actor.remained.present",
                    modality="sight",
                    location_id=state.actor_locations.get(
                        actor.oc_id,
                        actor.location_id,
                    ),
                    line_of_sight_required=True,
                    data={"actorId": proposal.actor_id},
                )
            ],
        )
        return Resolution.model_construct(decision=decision, event=event)

    def resolve_dm(
        self,
        proposal: DmProposal,
        state: WorldState,
        *,
        sequence: int,
        decision_id: str,
        canonical_event_id: str,
    ) -> Resolution:
        template = next(
            (
                candidate
                for candidate in self.world.scenario_catalog
                if candidate.template_id == proposal.template_id
            ),
            None,
        )
        if template is None or template.kind != proposal.kind:
            return self._seal(
                proposal,
                state,
                self._invalid(
                    proposal.proposal_id,
                    decision_id,
                    "DM_TEMPLATE_NOT_ALLOWED",
                ),
            )
        countdown_rule = self.world.rule("COUNTDOWN")
        if (
            proposal.kind != "PRESSURE"
            or countdown_rule is None
            or not countdown_rule.enabled
        ):
            return self._seal(
                proposal,
                state,
                self._invalid(
                    proposal.proposal_id,
                    decision_id,
                    "DM_INTERVENTION_NOT_EXECUTABLE",
                ),
            )
        countdown = int(
            proposal.params.get(
                "countdown",
                countdown_rule.params.get("ticks", 3),
            )
        )
        decision = RuleDecision(
            decision_id=decision_id,
            proposal_id=proposal.proposal_id,
            verdict="resolved",
            outcome="success",
            matched_rule_ids=[countdown_rule.rule_id],
            reason_codes=["DM_TEMPLATE_ALLOWED"],
        )
        event = CanonicalEvent(
            canonical_event_id=canonical_event_id,
            sequence=sequence,
            kind="dm.intervention.applied",
            decision_id=decision_id,
            fact_codes=["countdown.started"],
            effects=[
                StateEffect(
                    op="set",
                    path="/countdown",
                    before=state.countdown,
                    after=countdown,
                )
            ],
            perceptual_atoms=[
                PerceptualAtom(
                    atom_id=f"{canonical_event_id}-bell",
                    code="foyer.bell.rang",
                    modality="hearing",
                    location_id="grand-foyer",
                    line_of_sight_required=False,
                    data={"countdown": countdown},
                )
            ],
        )
        return self._seal(
            proposal,
            state,
            Resolution.model_construct(decision=decision, event=event),
        )

    def resolve_utterance(
        self,
        proposal: UtteranceProposal,
        state: WorldState,
        *,
        sequence: int,
        decision_id: str,
        canonical_event_id: str,
    ) -> Resolution:
        try:
            actor = self.world.character(proposal.actor_id)
        except StopIteration:
            return self._seal(
                proposal,
                state,
                self._invalid(
                    proposal.proposal_id,
                    decision_id,
                    "ACTOR_NOT_FOUND",
                ),
            )

        social_rule = self.world.rule("SOCIAL_CONSEQUENCE")
        effects: list[StateEffect] = []
        matched_rule_ids: list[str] = []
        if social_rule and social_rule.enabled:
            target_by_actor = social_rule.params.get("targetByActor", {})
            target_id = target_by_actor.get(proposal.actor_id)
            if target_id and target_id in state.relationships.get(actor.oc_id, {}):
                relationship = state.relationships[actor.oc_id][target_id]
                delta = int(social_rule.params.get("tensionDelta", 1))
                after = max(-3, min(3, relationship.tension + delta))
                applied_delta = after - relationship.tension
                if applied_delta:
                    effects.append(
                        StateEffect(
                            op="inc",
                            path=(
                                f"/relationships/{actor.oc_id}/{target_id}/tension"
                            ),
                            before=relationship.tension,
                            by=applied_delta,
                            after=after,
                        )
                    )
                    matched_rule_ids.append(social_rule.rule_id)

        decision = RuleDecision(
            decision_id=decision_id,
            proposal_id=proposal.proposal_id,
            verdict="resolved",
            outcome="success",
            matched_rule_ids=matched_rule_ids,
            reason_codes=["UTTERANCE_ALLOWED", "CLAIM_NOT_PROMOTED_TO_FACT"],
        )
        event = CanonicalEvent(
            canonical_event_id=canonical_event_id,
            sequence=sequence,
            kind="utterance.spoken",
            actor_id=proposal.actor_id,
            decision_id=decision_id,
            fact_codes=["utterance.spoken"],
            effects=effects,
            perceptual_atoms=[
                PerceptualAtom(
                    atom_id=f"{canonical_event_id}-heard",
                    code="utterance.heard",
                    modality="hearing",
                    location_id=state.actor_locations.get(
                        actor.oc_id,
                        actor.location_id,
                    ),
                    line_of_sight_required=False,
                    data={
                        "speakerId": proposal.actor_id,
                        "text": proposal.text,
                    },
                )
            ],
        )
        return self._seal(
            proposal,
            state,
            Resolution.model_construct(decision=decision, event=event),
        )

    def _resolve_take(
        self,
        proposal: CharacterProposal,
        state: WorldState,
        sequence: int,
        decision_id: str,
        canonical_event_id: str,
    ) -> Resolution:
        action = proposal.action
        if action.kind != "TAKE":
            raise DomainInvariantError("TAKE resolver received a non-TAKE action")
        world_object = state.objects[action.object_id]
        rule = self.world.rule("CONSENTED_TRANSFER_ONLY")
        consent_required = bool(
            rule
            and rule.enabled
            and rule.params.get("consentRequired", True)
        )
        matched = [rule.rule_id] if rule else []

        if consent_required:
            legacy_key = "threshold-key" in world_object.tags
            decision = RuleDecision(
                decision_id=decision_id,
                proposal_id=proposal.proposal_id,
                verdict="resolved",
                outcome="blocked",
                matched_rule_ids=matched,
                reason_codes=["CONSENT_REQUIRED"],
            )
            event = CanonicalEvent(
                canonical_event_id=canonical_event_id,
                sequence=sequence,
                kind="action.resolved",
                actor_id=proposal.actor_id,
                decision_id=decision_id,
                fact_codes=(
                    ["key.take.blocked", "key.holder.unchanged"]
                    if legacy_key
                    else ["object.take.blocked", "object.holder.unchanged"]
                ),
                effects=[],
                perceptual_atoms=self._object_atoms(
                    canonical_event_id,
                    actor_id=proposal.actor_id,
                    object_id=action.object_id,
                    location_id=state.actor_locations.get(
                        proposal.actor_id,
                        self.world.character(proposal.actor_id).location_id,
                    ),
                    sight_code=(
                        "key.resisted.take"
                        if legacy_key
                        else "object.resisted.take"
                    ),
                    sound_code=(
                        "key.metal.chime"
                        if legacy_key
                        else "object.contact.heard"
                    ),
                ),
            )
            return Resolution.model_construct(decision=decision, event=event)

        decision = RuleDecision(
            decision_id=decision_id,
            proposal_id=proposal.proposal_id,
            verdict="resolved",
            outcome="success",
            matched_rule_ids=matched,
            reason_codes=["CONSENT_NOT_REQUIRED"],
        )
        legacy_key = "threshold-key" in world_object.tags
        event = CanonicalEvent(
            canonical_event_id=canonical_event_id,
            sequence=sequence,
            kind="action.resolved",
            actor_id=proposal.actor_id,
            decision_id=decision_id,
            fact_codes=["key.taken"] if legacy_key else ["object.taken"],
            effects=[
                StateEffect(
                    op="set",
                    path=f"/objects/{action.object_id}/holderId",
                    before=world_object.holder_id,
                    after=proposal.actor_id,
                )
            ],
            perceptual_atoms=self._object_atoms(
                canonical_event_id,
                actor_id=proposal.actor_id,
                object_id=action.object_id,
                location_id=state.actor_locations.get(
                    proposal.actor_id,
                    self.world.character(proposal.actor_id).location_id,
                ),
                sight_code="key.take.seen" if legacy_key else "object.take.seen",
                sound_code=(
                    "key.metal.chime"
                    if legacy_key
                    else "object.contact.heard"
                ),
            ),
        )
        return Resolution.model_construct(decision=decision, event=event)

    def _resolve_give(
        self,
        proposal: CharacterProposal,
        state: WorldState,
        sequence: int,
        decision_id: str,
        canonical_event_id: str,
    ) -> Resolution:
        action = proposal.action
        if action.kind != "GIVE":
            raise DomainInvariantError("GIVE resolver received a non-GIVE action")
        world_object = state.objects[action.object_id]
        if world_object.holder_id != proposal.actor_id:
            return self._invalid(
                proposal.proposal_id,
                decision_id,
                "ACTOR_IS_NOT_CURRENT_HOLDER",
            )
        if not any(
            character.oc_id == action.recipient_id
            for character in self.world.characters
        ):
            return self._invalid(
                proposal.proposal_id,
                decision_id,
                "RECIPIENT_NOT_FOUND",
            )

        rule = self.world.rule("CONSENTED_TRANSFER_ONLY")
        matched = [rule.rule_id] if rule and rule.enabled else []
        decision = RuleDecision(
            decision_id=decision_id,
            proposal_id=proposal.proposal_id,
            verdict="resolved",
            outcome="success",
            matched_rule_ids=matched,
            reason_codes=["CURRENT_HOLDER_GAVE_VOLUNTARILY"],
        )
        actor = self.world.character(proposal.actor_id)
        legacy_key = "threshold-key" in world_object.tags
        location_id = state.actor_locations.get(actor.oc_id, actor.location_id)
        event = CanonicalEvent(
            canonical_event_id=canonical_event_id,
            sequence=sequence,
            kind="action.resolved",
            actor_id=proposal.actor_id,
            decision_id=decision_id,
            fact_codes=(
                ["key.transferred.voluntarily"]
                if legacy_key
                else ["object.transferred.voluntarily"]
            ),
            effects=[
                StateEffect(
                    op="set",
                    path=f"/objects/{action.object_id}/holderId",
                    before=proposal.actor_id,
                    after=action.recipient_id,
                )
            ],
            perceptual_atoms=[
                PerceptualAtom(
                    atom_id=f"{canonical_event_id}-seen",
                    code=(
                        "key.transfer.seen"
                        if legacy_key
                        else "object.transfer.seen"
                    ),
                    modality="sight",
                    location_id=location_id,
                    line_of_sight_required=True,
                    data={
                        "actorId": proposal.actor_id,
                        "recipientId": action.recipient_id,
                        "objectId": action.object_id,
                        "voluntary": True,
                    },
                ),
                PerceptualAtom(
                    atom_id=f"{canonical_event_id}-heard",
                    code=(
                        "key.metal.chime"
                        if legacy_key
                        else "object.contact.heard"
                    ),
                    modality="hearing",
                    location_id=location_id,
                    line_of_sight_required=False,
                    data={"objectId": action.object_id},
                ),
            ],
        )
        return Resolution.model_construct(decision=decision, event=event)

    def _resolve_move(
        self,
        proposal: CharacterProposal,
        state: WorldState,
        sequence: int,
        decision_id: str,
        canonical_event_id: str,
    ) -> Resolution:
        action = proposal.action
        if action.kind != "MOVE":
            raise DomainInvariantError("MOVE resolver received a non-MOVE action")
        try:
            actor = self.world.character(proposal.actor_id)
            destination = self.world.location(action.location_id)
        except StopIteration:
            return self._invalid(
                proposal.proposal_id,
                decision_id,
                "LOCATION_NOT_FOUND",
            )
        stored_location = state.actor_locations.get(proposal.actor_id)
        current_location_id = stored_location or actor.location_id
        try:
            current = self.world.location(current_location_id)
        except StopIteration:
            return self._invalid(
                proposal.proposal_id,
                decision_id,
                "CURRENT_LOCATION_NOT_FOUND",
            )
        rule = self.world.rule("LOCATION_TRANSITION")
        if rule is None or not rule.enabled:
            return self._invalid(
                proposal.proposal_id,
                decision_id,
                "LOCATION_TRANSITION_NOT_ALLOWED",
            )
        if current.location_id == destination.location_id:
            return self._invalid(
                proposal.proposal_id,
                decision_id,
                "ALREADY_AT_LOCATION",
            )
        if current.layer == "adventure" and destination.layer == "adventure":
            return self._invalid(
                proposal.proposal_id,
                decision_id,
                "ADVENTURE_TO_ADVENTURE_NOT_SUPPORTED",
            )
        if (
            current.layer == "adventure"
            and current.return_location_id
            and destination.location_id != current.return_location_id
        ):
            return self._invalid(
                proposal.proposal_id,
                decision_id,
                "ADVENTURE_MUST_RETURN_TO_SAFE_ORIGIN",
            )

        decision = RuleDecision(
            decision_id=decision_id,
            proposal_id=proposal.proposal_id,
            verdict="resolved",
            outcome="success",
            matched_rule_ids=[rule.rule_id],
            reason_codes=[
                "VOLUNTARY_LOCATION_TRANSITION",
                f"{current.layer.upper()}_TO_{destination.layer.upper()}",
            ],
        )
        event = CanonicalEvent(
            canonical_event_id=canonical_event_id,
            sequence=sequence,
            kind="action.resolved",
            actor_id=proposal.actor_id,
            decision_id=decision_id,
            fact_codes=[
                "location.transitioned",
                f"location.layer.{destination.layer}",
            ],
            effects=[
                StateEffect(
                    op="set",
                    path=f"/actorLocations/{proposal.actor_id}",
                    before=stored_location,
                    after=destination.location_id,
                )
            ],
            perceptual_atoms=[
                PerceptualAtom(
                    atom_id=f"{canonical_event_id}-departure",
                    code="location.departure.seen",
                    modality="sight",
                    location_id=current.location_id,
                    line_of_sight_required=True,
                    data={
                        "actorId": proposal.actor_id,
                        "fromLocationId": current.location_id,
                    },
                ),
                PerceptualAtom(
                    atom_id=f"{canonical_event_id}-arrival",
                    code="location.arrival.experienced",
                    modality="sight",
                    location_id=destination.location_id,
                    line_of_sight_required=True,
                    data={
                        "actorId": proposal.actor_id,
                        "toLocationId": destination.location_id,
                        "layer": destination.layer,
                    },
                ),
            ],
        )
        return Resolution.model_construct(decision=decision, event=event)

    @staticmethod
    def _object_atoms(
        canonical_event_id: str,
        *,
        actor_id: str,
        object_id: str,
        location_id: str,
        sight_code: str,
        sound_code: str,
    ) -> list[PerceptualAtom]:
        return [
            PerceptualAtom(
                atom_id=f"{canonical_event_id}-seen",
                code=sight_code,
                modality="sight",
                location_id=location_id,
                line_of_sight_required=True,
                data={"actorId": actor_id, "objectId": object_id},
            ),
            PerceptualAtom(
                atom_id=f"{canonical_event_id}-heard",
                code=sound_code,
                modality="hearing",
                location_id=location_id,
                line_of_sight_required=False,
                data={"objectId": object_id},
            ),
        ]

    @staticmethod
    def _invalid(
        proposal_id: str,
        decision_id: str,
        reason_code: str,
    ) -> Resolution:
        return Resolution.model_construct(
            decision=RuleDecision(
                decision_id=decision_id,
                proposal_id=proposal_id,
                verdict="reject_invalid",
                matched_rule_ids=[],
                reason_codes=[reason_code],
            ),
            event=None,
        )

    def _seal(
        self,
        proposal: BaseModel,
        state: WorldState,
        resolution: Resolution,
    ) -> Resolution:
        event = resolution.event
        matched_rules = [
            rule
            for rule_id in resolution.decision.matched_rule_ids
            for rule in self.world.rules
            if rule.rule_id == rule_id
        ]
        proposal_fingerprint = _fingerprint(proposal)
        rule_fingerprint = _fingerprint(matched_rules)
        effects_fingerprint = _fingerprint(event.effects if event else [])
        event_fingerprint = _fingerprint(event) if event else None
        receipt_payload = {
            "proposalId": resolution.decision.proposal_id,
            "proposalFingerprint": proposal_fingerprint,
            "decisionId": resolution.decision.decision_id,
            "verdict": resolution.decision.verdict,
            "outcome": resolution.decision.outcome,
            "matchedRuleIds": resolution.decision.matched_rule_ids,
            "reasonCodes": resolution.decision.reason_codes,
            "inputWorldVersion": state.world_version,
            "ruleFingerprint": rule_fingerprint,
            "effectsFingerprint": effects_fingerprint,
            "canonicalEventId": event.canonical_event_id if event else None,
            "canonicalEventFingerprint": event_fingerprint,
        }
        receipt_id = f"{resolution.decision.decision_id}-receipt"
        receipt_fingerprint = _fingerprint(receipt_payload)
        issuer_signature = self._authority.sign(
            {
                "receiptId": receipt_id,
                **receipt_payload,
                "receiptFingerprint": receipt_fingerprint,
            }
        )
        receipt = ResolutionReceipt(
            receipt_id=receipt_id,
            **receipt_payload,
            receipt_fingerprint=receipt_fingerprint,
            issuer_signature=issuer_signature,
        )
        return Resolution(
            decision=resolution.decision,
            event=event,
            receipt=receipt,
        )


def _fingerprint(value: object) -> str:
    if isinstance(value, BaseModel):
        value = value.model_dump(
            by_alias=True,
            exclude_none=False,
            mode="json",
        )
    elif isinstance(value, list):
        value = [
            item.model_dump(
                by_alias=True,
                exclude_none=False,
                mode="json",
            )
            if isinstance(item, BaseModel)
            else item
            for item in value
        ]
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


class ResolutionAuthority:
    """Ephemeral capability used to distinguish the runtime's bound kernel."""

    def __init__(self) -> None:
        self.__key = secrets.token_bytes(32)

    def sign(self, value: object) -> str:
        return hmac.new(
            self.__key,
            _canonical_bytes(value),
            hashlib.sha256,
        ).hexdigest()

    def verifies(self, value: object, signature: str) -> bool:
        return hmac.compare_digest(self.sign(value), signature)


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
