export type PortraitImageFactory = () => HTMLImageElement;

const createBrowserImage: PortraitImageFactory = () => new Image();

export function warmPortraitCache(
  urls: Iterable<string>,
  createImage: PortraitImageFactory = createBrowserImage,
): HTMLImageElement[] {
  return [...new Set(urls)].map((url) => {
    const image = createImage();
    image.decoding = "async";
    image.fetchPriority = "low";
    image.src = url;
    if (typeof image.decode === "function") {
      void image.decode().catch(() => undefined);
    }
    return image;
  });
}
