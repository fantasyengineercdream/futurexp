from __future__ import annotations

from app.domain.models import Belief, MindProjection, Observation, PrivateOs


class DeterministicMindPolicy:
    """Credential-free policy with the same shape as a future model adapter."""

    def interpret(self, observation: Observation) -> MindProjection:
        codes = {fact.code for fact in observation.facts}
        source_ids = [observation.observation_id]

        if observation.oc_id == "oc-angel" and "key.metal.chime" in codes:
            belief = Belief(
                belief_id=f"belief-{observation.observation_id}",
                oc_id=observation.oc_id,
                predicate="keyWasTakenBy",
                object="oc-devil",
                stance="believed",
                confidence=0.72,
                source_observation_ids=source_ids,
            )
            return MindProjection(belief=belief)

        sight_fact = next(
            (fact for fact in observation.facts if fact.code == "key.transfer.seen"),
            None,
        )
        if observation.oc_id == "oc-user" and sight_fact:
            belief = Belief(
                belief_id=f"belief-{observation.observation_id}",
                oc_id=observation.oc_id,
                predicate="voluntarilyGaveKeyTo",
                object=sight_fact.data["recipientId"],
                stance="believed",
                confidence=1,
                source_observation_ids=source_ids,
            )
            private_os = PrivateOs(
                private_os_id=f"private-os-{observation.observation_id}",
                oc_id=observation.oc_id,
                canonical_event_id=observation.canonical_event_id,
                text="是我亲手交给他的。先别让天使知道。",
                based_on_belief_ids=[belief.belief_id],
            )
            return MindProjection(belief=belief, private_os=private_os)

        if observation.oc_id == "oc-devil" and sight_fact:
            belief = Belief(
                belief_id=f"belief-{observation.observation_id}",
                oc_id=observation.oc_id,
                predicate="wasTrustedBy",
                object=sight_fact.data["actorId"],
                stance="believed",
                confidence=0.92,
                source_observation_ids=source_ids,
            )
            return MindProjection(belief=belief)

        belief = Belief(
            belief_id=f"belief-{observation.observation_id}",
            oc_id=observation.oc_id,
            predicate="noticedEvent",
            object=observation.canonical_event_id,
            stance="believed",
            confidence=0.5,
            source_observation_ids=source_ids,
        )
        return MindProjection(belief=belief)
