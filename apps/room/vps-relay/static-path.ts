import * as nativePath from "node:path";
import type { PlatformPath } from "node:path";

export function resolveStaticFile(
  rootDirectory: string,
  requestPath: string,
  pathApi: PlatformPath = nativePath,
): string | null {
  const root = pathApi.resolve(rootDirectory);
  const candidate =
    requestPath === "/"
      ? "index.html"
      : requestPath.replace(/^[/\\]+/, "");
  const filePath = pathApi.resolve(root, candidate);
  const relative = pathApi.relative(root, filePath);
  if (
    relative === ".."
    || relative.startsWith(`..${pathApi.sep}`)
    || pathApi.isAbsolute(relative)
  ) {
    return null;
  }
  return filePath;
}
