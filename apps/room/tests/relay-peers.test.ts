import { describe, expect, test } from "vitest";
import {
  RelayPeers,
  type RelayPeer,
} from "../relay-worker/src/relay-peers";

class TestPeer implements RelayPeer {
  readyState = 1;
  sent: Array<string | ArrayBuffer | Uint8Array> = [];
  closed?: { code: number; reason: string };

  send(data: string | ArrayBuffer | Uint8Array): void {
    this.sent.push(data);
  }

  close(code: number, reason: string): void {
    this.closed = { code, reason };
    this.readyState = 3;
  }
}

function messages(peer: TestPeer): unknown[] {
  return peer.sent
    .filter((item): item is string => typeof item === "string")
    .map((item) => JSON.parse(item));
}

describe("relay peers", () => {
  test("rejects a viewer while the device is offline", () => {
    const peers = new RelayPeers();
    const viewer = new TestPeer();

    expect(peers.attachViewer(viewer)).toBe("offline");
    expect(messages(viewer)).toEqual([
      { type: "device.offline", code: "device_unavailable" },
    ]);
    expect(viewer.closed).toEqual({
      code: 4410,
      reason: "device_unavailable",
    });
  });

  test("grants only one viewer and releases it on disconnect", () => {
    const peers = new RelayPeers();
    const device = new TestPeer();
    const owner = new TestPeer();
    const contender = new TestPeer();
    const replacement = new TestPeer();
    peers.attachDevice(device);

    expect(peers.attachViewer(owner)).toBe("ready");
    expect(messages(owner)).toEqual([
      { type: "session.ready", status: "acquired" },
    ]);
    expect(peers.attachViewer(contender)).toBe("busy");
    expect(messages(contender)).toEqual([
      { type: "session.busy", code: "ring_in_use" },
    ]);
    expect(contender.closed?.code).toBe(4409);

    peers.detachViewer(owner);
    expect(peers.attachViewer(replacement)).toBe("ready");
  });

  test("device disconnect notifies and closes the current viewer", () => {
    const peers = new RelayPeers();
    const device = new TestPeer();
    const viewer = new TestPeer();
    peers.attachDevice(device);
    peers.attachViewer(viewer);

    peers.detachDevice(device);

    expect(messages(viewer)).toContainEqual({
      type: "device.offline",
      code: "device_unavailable",
    });
    expect(viewer.closed?.code).toBe(4410);
  });

  test("device reconnect replaces the stale connection", () => {
    const peers = new RelayPeers();
    const first = new TestPeer();
    const second = new TestPeer();

    peers.attachDevice(first);
    peers.attachDevice(second);

    expect(first.closed).toEqual({
      code: 4001,
      reason: "device_replaced",
    });
    const viewer = new TestPeer();
    expect(peers.attachViewer(viewer)).toBe("ready");
  });

  test("sends viewer JSON and binary only to the owner", () => {
    const peers = new RelayPeers();
    const device = new TestPeer();
    const viewer = new TestPeer();
    peers.attachDevice(device);
    peers.attachViewer(viewer);

    peers.sendViewerJson({ type: "state", phase: "speaking" });
    peers.sendViewerBinary(new Uint8Array([1, 2]));

    expect(messages(viewer)).toContainEqual({
      type: "state",
      phase: "speaking",
    });
    expect(viewer.sent.at(-1)).toEqual(new Uint8Array([1, 2]));
    expect(device.sent).toEqual([]);
  });
});
