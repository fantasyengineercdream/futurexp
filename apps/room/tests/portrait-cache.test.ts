import { describe, expect, it, vi } from "vitest";
import { warmPortraitCache } from "../src/portrait-cache";

describe("portrait cache", () => {
  it("starts low-priority loading and decoding for every portrait", async () => {
    const images: Array<{
      decoding: string;
      fetchPriority: string;
      src: string;
      decode: ReturnType<typeof vi.fn>;
    }> = [];

    warmPortraitCache(["/devil.webp", "/angel.webp"], () => {
      const image = {
        decoding: "auto",
        fetchPriority: "auto",
        src: "",
        decode: vi.fn().mockResolvedValue(undefined),
      };
      images.push(image);
      return image as unknown as HTMLImageElement;
    });

    await Promise.resolve();
    expect(images.map((image) => image.src)).toEqual(["/devil.webp", "/angel.webp"]);
    expect(images.every((image) => image.decoding === "async")).toBe(true);
    expect(images.every((image) => image.fetchPriority === "low")).toBe(true);
    expect(images.map((image) => image.decode.mock.calls.length)).toEqual([1, 1]);
  });

  it("does not surface a browser decode rejection", async () => {
    const decode = vi.fn().mockRejectedValue(new Error("decode failed"));
    warmPortraitCache(["/portrait.webp"], () => ({
      decoding: "auto",
      fetchPriority: "auto",
      src: "",
      decode,
    }) as unknown as HTMLImageElement);

    await Promise.resolve();
    expect(decode).toHaveBeenCalledOnce();
  });
});
