export const RUNTIME_EVENT_TYPES = [
  "session.snapshot",
  "tick.started",
  "proposal.character.created",
  "proposal.dm.created",
  "proposal.utterance.created",
  "rule.decision.created",
  "canonical.event.committed",
  "observation.created",
  "belief.updated",
  "utterance.created",
  "privateOs.created",
  "tick.completed",
  "session.completed",
  "runtime.error",
] as const;

export type RuntimeEventType = (typeof RUNTIME_EVENT_TYPES)[number];
export type OcId = "oc-user" | "oc-angel" | "oc-devil";
export type Sha256 = string;
export type JsonValue =
  | null
  | boolean
  | number
  | string
  | JsonValue[]
  | { [key: string]: JsonValue };

export type Visibility =
  | { scope: "public" }
  | { scope: "owner"; ocId: OcId }
  | { scope: "actor"; ocId: OcId }
  | { scope: "tech" };

export interface RuntimeEventEnvelope<
  TType extends RuntimeEventType,
  TPayload,
> {
  schemaVersion: 1;
  eventId: string;
  cursor: number;
  sessionId: string;
  tickIndex: number;
  emittedAt: string;
  type: TType;
  visibility: Visibility;
  causationId?: string;
  payload: TPayload;
}

export interface Relationship {
  trust: number;
  affinity: number;
  tension: number;
}

export interface WorldObject {
  objectId: string;
  name: string;
  locationId: string;
  holderId: OcId | null;
  tags: string[];
}

export interface WorldState {
  worldId: "infinite-apartment";
  worldVersion: number;
  tickIndex: number;
  status: "ready" | "running" | "completed" | "failed";
  objects: Record<string, WorldObject>;
  thresholdUnlocked: boolean;
  countdown: number | null;
  relationships: Record<OcId, Partial<Record<OcId, Relationship>>>;
}

export interface CharacterProposal {
  proposalId: string;
  actorId: OcId;
  action:
    | { kind: "TAKE"; objectId: string }
    | { kind: "GIVE"; objectId: string; recipientId: OcId }
    | { kind: "ACCUSE"; targetId: OcId; claim: string };
  motivationRefs: string[];
  proposedPublicLine?: string;
}

export interface DmProposal {
  proposalId: string;
  templateId: string;
  kind: "PRESSURE" | "REVEAL_CUE" | "ADVANCE_CLOCK";
  params: Record<string, JsonValue>;
}

export interface UtteranceProposal {
  proposalId: string;
  actorId: OcId;
  text: string;
  audience: "world" | "owner" | "publicUi";
  basedOnBeliefIds: string[];
}

export interface RuleDecisionTrace {
  decisionId: string;
  proposalId: string;
  verdict: "reject_invalid" | "resolved";
  outcome?: "success" | "blocked" | "with_cost";
  matchedRuleIds: string[];
  reasonCodes: string[];
}

export type StateEffect =
  | { op: "set"; path: string; before: JsonValue; after: JsonValue }
  | {
      op: "inc";
      path: string;
      before: number;
      by: number;
      after: number;
    };

export interface PerceptualAtom {
  atomId: string;
  code: string;
  modality: "sight" | "hearing" | "system";
  locationId?: string;
  lineOfSightRequired: boolean;
  data: Record<string, JsonValue>;
}

export interface CanonicalEvent {
  canonicalEventId: string;
  sequence: number;
  kind:
    | "dm.intervention.applied"
    | "action.resolved"
    | "utterance.spoken"
    | "session.completed";
  actorId?: OcId;
  decisionId: string;
  factCodes: string[];
  effects: StateEffect[];
  perceptualAtoms: PerceptualAtom[];
}

export interface Observation {
  observationId: string;
  canonicalEventId: string;
  ocId: OcId;
  channels: Array<"sight" | "hearing" | "system">;
  facts: Array<{
    atomId: string;
    code: string;
    data: Record<string, JsonValue>;
  }>;
  completeness: "full" | "partial";
  source: "direct" | "reported";
}

export interface Belief {
  beliefId: string;
  ocId: OcId;
  predicate: string;
  object: JsonValue;
  stance: "suspected" | "believed" | "disbelieved";
  confidence: number;
  sourceObservationIds: string[];
}

export interface Utterance {
  utteranceId: string;
  ocId: OcId;
  canonicalEventId: string;
  audience: "world" | "owner" | "publicUi";
  text: string;
  basedOnBeliefIds: string[];
  truthPosture: "candid" | "uncertain" | "withholding" | "misrepresenting";
}

export interface PrivateOs {
  privateOsId: string;
  ocId: OcId;
  canonicalEventId: string;
  text: string;
  basedOnBeliefIds: string[];
  delivery: "ownerPrivate";
}

export interface SessionSnapshot {
  sessionId: string;
  worldVersion: number;
  tickIndex: number;
  lastCanonicalSequence: number;
  checksum: Sha256;
  state: WorldState;
}

export type RuntimeServerEvent =
  | RuntimeEventEnvelope<"session.snapshot", { snapshot: SessionSnapshot }>
  | RuntimeEventEnvelope<
      "tick.started",
      { actorId: OcId; worldVersion: number }
    >
  | RuntimeEventEnvelope<
      "proposal.character.created",
      { proposal: CharacterProposal }
    >
  | RuntimeEventEnvelope<"proposal.dm.created", { proposal: DmProposal }>
  | RuntimeEventEnvelope<
      "proposal.utterance.created",
      { proposal: UtteranceProposal }
    >
  | RuntimeEventEnvelope<
      "rule.decision.created",
      { decision: RuleDecisionTrace }
    >
  | RuntimeEventEnvelope<
      "canonical.event.committed",
      { event: CanonicalEvent; worldVersion: number }
    >
  | RuntimeEventEnvelope<"observation.created", { observation: Observation }>
  | RuntimeEventEnvelope<"belief.updated", { belief: Belief }>
  | RuntimeEventEnvelope<"utterance.created", { utterance: Utterance }>
  | RuntimeEventEnvelope<"privateOs.created", { privateOs: PrivateOs }>
  | RuntimeEventEnvelope<
      "tick.completed" | "session.completed",
      {
        worldVersion: number;
        lastCanonicalSequence: number;
        checksum: Sha256;
      }
    >
  | RuntimeEventEnvelope<
      "runtime.error",
      { code: string; message: string; recoverable: boolean }
    >;

export interface WorldRuleView {
  ruleId: string;
  kind: string;
  label: string;
  description: string;
  enabled: boolean;
  params: Record<string, JsonValue>;
}

export interface WorldInfoView {
  worldId: "infinite-apartment";
  name: "无限公寓";
  aesthetic: string;
  description: string;
  rules: WorldRuleView[];
}

export interface SessionViewBase {
  sessionId: string;
  worldId: "infinite-apartment";
  status: "running" | "completed" | "failed";
  consentRequired: boolean;
  lastCursor: number;
  events: RuntimeServerEvent[];
}

export interface WorldSessionView extends SessionViewBase {
  world: WorldInfoView;
}

export interface OwnerSessionView extends SessionViewBase {
  checksum: Sha256;
  oc: {
    ocId: "oc-user";
    name: string;
    role: string;
    persona: string;
    publicStyle: string;
  };
}

export interface ProofSessionView extends SessionViewBase {
  checksum: Sha256;
  objectiveState: WorldState;
}

export interface PassportView {
  ocId: "oc-user";
  worldId: "infinite-apartment";
  name: string;
  role: string;
  publicStyle: string;
  publicExperience: string;
}

export interface ErrorDto {
  code: string;
  message: string;
  retryable: boolean;
}
