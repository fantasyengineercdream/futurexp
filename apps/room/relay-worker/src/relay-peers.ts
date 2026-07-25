export interface RelayPeer {
  readonly readyState: number;
  send(data: string | ArrayBuffer | Uint8Array): void;
  close(code: number, reason: string): void;
}

export type ViewerAdmission = "ready" | "busy" | "offline";

const OPEN = 1;

export class RelayPeers {
  private device?: RelayPeer;
  private viewer?: RelayPeer;

  attachDevice(peer: RelayPeer): void {
    if (this.device && this.device !== peer) {
      this.device.close(4001, "device_replaced");
    }
    this.device = peer;
  }

  detachDevice(peer: RelayPeer): void {
    if (this.device !== peer) return;
    this.device = undefined;
    if (this.viewer) {
      this.sendViewerJson({
        type: "device.offline",
        code: "device_unavailable",
      });
      this.viewer.close(4410, "device_unavailable");
      this.viewer = undefined;
    }
  }

  attachViewer(peer: RelayPeer): ViewerAdmission {
    if (!this.device || this.device.readyState !== OPEN) {
      peer.send(
        JSON.stringify({
          type: "device.offline",
          code: "device_unavailable",
        }),
      );
      peer.close(4410, "device_unavailable");
      return "offline";
    }
    if (this.viewer && this.viewer.readyState === OPEN) {
      peer.send(
        JSON.stringify({
          type: "session.busy",
          code: "ring_in_use",
        }),
      );
      peer.close(4409, "ring_in_use");
      return "busy";
    }
    this.viewer = peer;
    peer.send(
      JSON.stringify({
        type: "session.ready",
        status: "acquired",
      }),
    );
    return "ready";
  }

  detachViewer(peer: RelayPeer): void {
    if (this.viewer === peer) this.viewer = undefined;
  }

  sendViewerJson(payload: Record<string, string>): void {
    if (!this.viewer || this.viewer.readyState !== OPEN) {
      this.viewer = undefined;
      return;
    }
    this.viewer.send(JSON.stringify(payload));
  }

  sendViewerBinary(payload: Uint8Array): void {
    if (!this.viewer || this.viewer.readyState !== OPEN) {
      this.viewer = undefined;
      return;
    }
    this.viewer.send(payload);
  }
}
