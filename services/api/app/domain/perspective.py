from __future__ import annotations

from app.domain.models import (
    CanonicalEvent,
    Observation,
    ObservationFact,
    WorldDefinition,
    WorldState,
)


class PerspectiveProjector:
    def __init__(self, world: WorldDefinition) -> None:
        self.world = world

    def project(
        self,
        event: CanonicalEvent,
        state: WorldState | None = None,
    ) -> dict[str, Observation]:
        observations: dict[str, Observation] = {}
        for character in self.world.characters:
            facts: list[ObservationFact] = []
            channels: list[str] = []
            observer_location_id = (
                state.actor_locations.get(
                    character.oc_id,
                    character.location_id,
                )
                if state is not None
                else character.location_id
            )
            for atom in event.perceptual_atoms:
                if atom.modality not in character.senses:
                    continue
                if (
                    atom.modality in {"sight", "hearing"}
                    and atom.location_id != observer_location_id
                ):
                    continue
                if atom.modality == "sight" and not self._can_see(
                    character.oc_id,
                    observer_location_id,
                    atom.location_id,
                ):
                    continue
                facts.append(
                    ObservationFact(
                        atom_id=atom.atom_id,
                        code=atom.code,
                        data=atom.data,
                    )
                )
                if atom.modality not in channels:
                    channels.append(atom.modality)

            has_hidden_atom = len(facts) < len(event.perceptual_atoms)
            observations[character.oc_id] = Observation(
                observation_id=(
                    f"observation-{event.canonical_event_id}-{character.oc_id}"
                ),
                canonical_event_id=event.canonical_event_id,
                oc_id=character.oc_id,
                channels=channels,
                facts=facts,
                completeness="partial" if has_hidden_atom else "full",
                source="direct",
            )
        return observations

    def _can_see(
        self,
        oc_id: str,
        observer_location_id: str,
        event_location_id: str | None,
    ) -> bool:
        if event_location_id is None or observer_location_id != event_location_id:
            return False
        location = self.world.location(event_location_id)
        return oc_id not in location.occludes_sight_for
