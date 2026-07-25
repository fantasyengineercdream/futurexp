export type AudioSourceKind = "browser" | "device";

type AcceptedSource = {
  accepted: true;
  openUpstream: boolean;
  activeSource: AudioSourceKind;
};

type RejectedSource = {
  accepted: false;
  reason: "browser_in_use" | "device_in_use";
  openUpstream: false;
  activeSource: AudioSourceKind;
};

export class RoomConnectionPolicy {
  private browserId?: string;
  private deviceId?: string;
  private viewerId?: string;
  private upstreamLease = false;

  get upstreamReserved(): boolean {
    return this.upstreamLease;
  }

  get activeSource(): AudioSourceKind | null {
    return this.resolveActiveSource();
  }

  attachSource(
    kind: AudioSourceKind,
    connectionId: string,
  ): AcceptedSource | RejectedSource {
    const existing = kind === "browser" ? this.browserId : this.deviceId;
    if (existing && existing !== connectionId) {
      return {
        accepted: false,
        reason: kind === "browser" ? "browser_in_use" : "device_in_use",
        openUpstream: false,
        activeSource: this.resolveActiveSource()!,
      };
    }

    if (kind === "browser") {
      this.browserId = connectionId;
    } else {
      this.deviceId = connectionId;
    }
    const openUpstream = !this.upstreamLease;
    this.upstreamLease = true;
    return {
      accepted: true,
      openUpstream,
      activeSource: this.resolveActiveSource()!,
    };
  }

  detachSource(
    kind: AudioSourceKind,
    connectionId: string,
  ): { activeSource: AudioSourceKind | null; closeUpstream: boolean } {
    if (kind === "browser" && this.browserId === connectionId) {
      this.browserId = undefined;
    }
    if (kind === "device" && this.deviceId === connectionId) {
      this.deviceId = undefined;
    }
    const activeSource = this.resolveActiveSource();
    const closeUpstream = activeSource === null && this.upstreamLease;
    if (closeUpstream) this.upstreamLease = false;
    return { activeSource, closeUpstream };
  }

  attachViewer(
    connectionId: string,
  ): { accepted: true } | { accepted: false; reason: "ring_in_use" } {
    if (this.viewerId && this.viewerId !== connectionId) {
      return { accepted: false, reason: "ring_in_use" };
    }
    this.viewerId = connectionId;
    return { accepted: true };
  }

  detachViewer(connectionId: string): void {
    if (this.viewerId === connectionId) this.viewerId = undefined;
  }

  private resolveActiveSource(): AudioSourceKind | null {
    if (this.browserId) return "browser";
    if (this.deviceId) return "device";
    return null;
  }
}
