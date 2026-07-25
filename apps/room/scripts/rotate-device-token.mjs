import { randomBytes } from "node:crypto";
import { spawnSync } from "node:child_process";
import {
  existsSync,
  mkdirSync,
  readFileSync,
  writeFileSync,
} from "node:fs";
import { join, resolve } from "node:path";

const privateRoot = process.env.OC_PRIVATE_DIR?.trim();
if (!privateRoot) {
  throw new Error("OC_PRIVATE_DIR is required");
}

const outputDirectory = resolve(privateRoot);
const outputPath = join(
  outputDirectory,
  "oc-hardware-device.generated.env",
);

mkdirSync(outputDirectory, { recursive: true });
let token;
if (existsSync(outputPath)) {
  if (process.env.OC_ROTATE_REUSE !== "1") {
    throw new Error(
      `Private handoff file already exists: ${outputPath}`,
    );
  }
  const match = readFileSync(outputPath, "utf8").match(
    /^OC_DEVICE_TOKEN=(ocdt_[A-Za-z0-9_-]+)$/m,
  );
  if (!match) {
    throw new Error("Existing private handoff file is invalid");
  }
  token = match[1];
} else {
  token = `ocdt_${randomBytes(32).toString("base64url")}`;
  writeFileSync(
    outputPath,
    [
      "OC_CLOUD_BASE_URL=https://oc-voice-lab.pages.dev",
      `OC_DEVICE_TOKEN=${token}`,
      "",
    ].join("\n"),
    {
      encoding: "utf8",
      flag: "wx",
      mode: 0o600,
    },
  );
}

const executable = process.platform === "win32" ? "npx.cmd" : "npx";
const result = spawnSync(
  executable,
  [
    "wrangler",
    "pages",
    "secret",
    "put",
    "DEVICE_TOKEN",
    "--project-name",
    "oc-voice-lab",
  ],
  {
    cwd: resolve(import.meta.dirname, ".."),
    input: `${token}\n`,
    encoding: "utf8",
    shell: process.platform === "win32",
    stdio: ["pipe", "pipe", "pipe"],
  },
);

if (result.status !== 0) {
  const diagnostic = (
    result.error?.message
    || result.stderr
    || result.stdout
    || "unknown error"
  )
    .replaceAll(token, "[redacted]")
    .trim();
  throw new Error(
    `Cloudflare secret update failed: ${diagnostic}`,
  );
}

console.log(`Cloudflare DEVICE_TOKEN updated.`);
console.log(`Private handoff file: ${outputPath}`);
