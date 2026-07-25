/**
 * Network-facing shared-universe contracts.
 *
 * This module is additive. The local Demo continues to use runtime.ts and its
 * four-scope Visibility union until a transport explicitly opts into these
 * contracts.
 */

export const SHARED_UNIVERSE_SCHEMA_VERSIONS = [
  "oc.identity/v1",
  "oc.canon-revision/v1",
  "world.instance/v1",
  "character.presence/v1",
  "capability.grant/v1",
  "capability.revocation/v1",
  "invitation/v1",
  "projection.policy/v1",
  "shared.event/v1",
  "portable-memory.summary/v1",
  "ai.request/v1",
  "ai.result/v1",
] as const;

export type SharedUniverseSchemaVersion =
  (typeof SHARED_UNIVERSE_SCHEMA_VERSIONS)[number];
export type UUID = `${string}-${string}-${string}-${string}-${string}`;
export type IsoDateTime = string;
export type JsonValue =
  | null
  | boolean
  | number
  | string
  | JsonValue[]
  | { [key: string]: JsonValue };
export type JsonObject = { [key: string]: JsonValue };

export interface OCIdentityV1 {
  schemaVersion: "oc.identity/v1";
  ocId: UUID;
  /** Display/discovery label only. Never an authorization key. */
  slug: string;
  createdAt: IsoDateTime;
  activeCanonRevisionId: UUID;
}

export interface CanonRevisionV1 {
  schemaVersion: "oc.canon-revision/v1";
  canonRevisionId: UUID;
  ocId: UUID;
  revision: number;
  displayName: string;
  publicProfile: JsonObject;
  createdAt: IsoDateTime;
}

export interface WorldInstanceV1 {
  schemaVersion: "world.instance/v1";
  worldInstanceId: UUID;
  worldDefinitionId: UUID;
  worldDefinitionVersion: string;
  slug: string;
  createdAt: IsoDateTime;
}

export interface CharacterPresenceV1 {
  schemaVersion: "character.presence/v1";
  presenceId: UUID;
  worldInstanceId: UUID;
  ocId: UUID;
  canonRevisionId: UUID;
  status: "invited" | "admitted" | "departed";
  runtimeStateRef: string;
  admittedAt?: IsoDateTime;
  departedAt?: IsoDateTime;
}

export interface CapabilityGrantV1 {
  schemaVersion: "capability.grant/v1";
  grantId: UUID;
  subjectPrincipalId: UUID;
  issuerPrincipalId: UUID;
  worldInstanceId: UUID;
  invitationId?: UUID;
  capabilities: string[];
  policyVersion: number;
  issuedAt: IsoDateTime;
  expiresAt: IsoDateTime;
}

export interface CapabilityRevocationV1 {
  schemaVersion: "capability.revocation/v1";
  revocationId: UUID;
  grantId: UUID;
  revokedByPrincipalId: UUID;
  reason: string;
  revokedAt: IsoDateTime;
}

export interface InvitationV1 {
  schemaVersion: "invitation/v1";
  invitationId: UUID;
  worldInstanceId: UUID;
  ocId: UUID;
  invitedByPrincipalId: UUID;
  invitedPrincipalId: UUID;
  status: "pending" | "accepted" | "rejected" | "expired" | "revoked";
  discoverySource: "nfc" | "qr" | "link" | "directory";
  issuedAt: IsoDateTime;
  expiresAt: IsoDateTime;
  acceptedAt?: IsoDateTime;
}

export type AudienceSelectorV1 =
  | { kind: "public" }
  | { kind: "world_members" }
  | { kind: "principals"; principalIds: UUID[] }
  | { kind: "capability_holders"; capability: string }
  | { kind: "none" }
  | { kind: "legacy_demo"; legacyRefs: string[] };

interface ProjectionPolicyBaseV1 {
  schemaVersion: "projection.policy/v1";
  policyVersion: number;
}

type SensitivityV1 =
  | "public"
  | "member"
  | "confidential"
  | "restricted"
  | "private";
type NonPrivateOsDataClassV1 =
  | "world_event"
  | "world_observation"
  | "portable_memory"
  | "operator_diagnostic";
type NativeRestrictedAudienceV1 = Exclude<
  AudienceSelectorV1,
  { kind: "public" } | { kind: "legacy_demo" }
>;

export type ProjectionPolicyV1 =
  | (ProjectionPolicyBaseV1 & {
      sensitivity: "public";
      dataClass: NonPrivateOsDataClassV1;
      audienceSelector: { kind: "public" };
      grantRefs: UUID[];
      compatibilityMode?: never;
    })
  | (ProjectionPolicyBaseV1 & {
      sensitivity: SensitivityV1;
      dataClass: NonPrivateOsDataClassV1;
      audienceSelector: NativeRestrictedAudienceV1;
      grantRefs: UUID[];
      compatibilityMode?: never;
    })
  | (ProjectionPolicyBaseV1 & {
      sensitivity: "private";
      dataClass: "private_os";
      audienceSelector: { kind: "principals"; principalIds: UUID[] };
      grantRefs: [UUID, ...UUID[]];
      compatibilityMode?: never;
    })
  | (ProjectionPolicyBaseV1 & {
      sensitivity: SensitivityV1;
      dataClass: NonPrivateOsDataClassV1;
      audienceSelector: { kind: "legacy_demo"; legacyRefs: string[] };
      grantRefs: UUID[];
      /** Local v1 adapter output is never accepted as network authorization. */
      compatibilityMode: "demo-v1";
    });

export interface SharedEventEnvelopeV1 {
  schemaVersion: "shared.event/v1";
  eventId: UUID;
  worldInstanceId: UUID;
  sequence: number;
  occurredAt: IsoDateTime;
  type: string;
  subjectOcId?: UUID;
  projectionPolicy: ProjectionPolicyV1;
  capabilityVersion: string;
  idempotencyKey: string;
  cancellationKey?: string;
  causationId?: UUID;
  payload: JsonObject;
}

export interface PortableMemorySummaryV1 {
  schemaVersion: "portable-memory.summary/v1";
  memorySummaryId: UUID;
  ocId: UUID;
  sourceWorldInstanceId: UUID;
  sourceEventIds: UUID[];
  summary: string;
  approvedByPrincipalId: UUID;
  createdAt: IsoDateTime;
}

export interface AiRequestV1 {
  schemaVersion: "ai.request/v1";
  requestId: UUID;
  capability: string;
  capabilityVersion: string;
  idempotencyKey: string;
  cancellationKey?: string;
  input: JsonObject;
}

export interface AiResultV1 {
  schemaVersion: "ai.result/v1";
  status: "remote" | "fallback";
  output: JsonObject;
  remoteErrorCode?: string;
}
