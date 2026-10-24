// Launch `tauri dev` against the backend port selected by `pm ui --port`.
//
// tauri.conf.json has a static devUrl/window URL (127.0.0.1:8000). Tauri's
// `--config` flag performs a JSON merge; we clone the checked-in config and
// override both URLs so no other window settings (size, decorations, tray)
// are lost.
import { spawn } from "node:child_process";
import { mkdtempSync, readFileSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

const port = process.env.PALIMIND_API_PORT || "8000";
const url = `http://127.0.0.1:${port}/ui`;

const baseConfigPath = join(process.cwd(), "src-tauri", "tauri.conf.json");
const config = JSON.parse(readFileSync(baseConfigPath, "utf8"));
config.build = { ...(config.build || {}), devUrl: url };
if (Array.isArray(config.app?.windows) && config.app.windows.length > 0) {
  config.app.windows[0] = { ...config.app.windows[0], url };
} else {
  config.app = { ...(config.app || {}), windows: [{ url }] };
}

const dir = mkdtempSync(join(tmpdir(), "palimind-tauri-"));
const overridePath = join(dir, "tauri.override.json");
writeFileSync(overridePath, JSON.stringify(config, null, 2));

const tauri = process.platform === "win32" ? "tauri.cmd" : "tauri";
const child = spawn(tauri, ["dev", "--config", overridePath], {
  stdio: "inherit",
  env: process.env,
  shell: process.platform === "win32",
});

child.on("exit", (code, signal) => {
  if (signal) process.kill(process.pid, signal);
  process.exit(code ?? 0);
});
