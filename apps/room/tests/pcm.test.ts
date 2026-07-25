import { expect, it } from "vitest";
import { floatToPcm16, resampleLinear } from "../src/pcm";

it("clamps float samples to PCM16", () => {
  expect([...floatToPcm16(new Float32Array([-2, 0, 2]))]).toEqual([-32768, 0, 32767]);
});

it("resamples 48 kHz audio to 24 kHz", () => {
  const source = Float32Array.from({ length: 480 }, (_, index) => index / 480);
  expect(resampleLinear(source, 48000)).toHaveLength(240);
});
