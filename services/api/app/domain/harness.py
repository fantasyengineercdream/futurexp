from __future__ import annotations

from app.domain.encounters import (
    Affordance,
    DramaticPressure,
    EncounterEngine,
    EncounterFrame,
)
from app.domain.models import (
    CharacterProposal,
    Resolution,
    UtteranceProposal,
    WorldDefinition,
    WorldState,
)
from app.domain.rules import RuleKernel
from app.domain.scheduler import DeterministicStepScheduler


class LivingWorldHarness:
    """Finite loop boundary between scheduling, choice, and adjudication."""

    def __init__(
        self,
        world: WorldDefinition,
        scheduler: DeterministicStepScheduler,
        *,
        encounter_engine: EncounterEngine | None = None,
    ) -> None:
        self.world = world
        self.scheduler = scheduler
        self.encounter_engine = encounter_engine or EncounterEngine()
        self.rule_kernel = RuleKernel(world)

    def next_encounter(
        self,
        state: WorldState,
        pressures: list[DramaticPressure],
    ) -> EncounterFrame | None:
        step = self.scheduler.pop_next()
        if step is None:
            return None
        return self.encounter_engine.generate(
            self.world,
            state,
            step,
            pressures,
        )

    def adjudicate(
        self,
        state: WorldState,
        affordance: Affordance,
        proposal: CharacterProposal | UtteranceProposal,
        *,
        sequence: int,
        decision_id: str,
        canonical_event_id: str,
    ) -> Resolution:
        self.encounter_engine.assert_proposal_allowed(affordance, proposal)
        if isinstance(proposal, UtteranceProposal):
            return self.rule_kernel.resolve_utterance(
                proposal,
                state,
                sequence=sequence,
                decision_id=decision_id,
                canonical_event_id=canonical_event_id,
            )
        return self.rule_kernel.resolve_character(
            proposal,
            state,
            sequence=sequence,
            decision_id=decision_id,
            canonical_event_id=canonical_event_id,
        )
