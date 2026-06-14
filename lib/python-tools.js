import { spawn, spawnSync } from "node:child_process";
import { accessSync, constants } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
export const packageRoot = resolve(here, "..");
export const skillRoot = join(packageRoot, "plugins", "sap-architecture", "skills", "sap-architecture");
export const scriptsDir = join(skillRoot, "scripts");

export function scriptPath(name) {
  return join(scriptsDir, name.endsWith(".py") ? name : `${name}.py`);
}

export function pythonCommand() {
  return process.env.BTP_DRAWIO_PYTHON || "python3";
}

export function checkPython() {
  const candidates = [pythonCommand(), "python", "py"];
  const seen = new Set();
  for (const command of candidates) {
    if (!command || seen.has(command)) continue;
    seen.add(command);
    const proc = spawnSync(command, ["--version"], { encoding: "utf8" });
    if (proc.status === 0) {
      return { command, version: (proc.stdout || proc.stderr).trim() };
    }
  }
  return null;
}

export function assertScript(name) {
  const path = scriptPath(name);
  accessSync(path, constants.R_OK);
  return path;
}

export function runPython(script, args = [], options = {}) {
  const command = pythonCommand();
  const timeoutMs = options.timeoutMs ?? 120_000;
  const cwd = options.cwd ?? packageRoot;
  return new Promise((resolveResult) => {
    const child = spawn(command, [assertScript(script), ...args], {
      cwd,
      env: process.env,
      stdio: ["ignore", "pipe", "pipe"]
    });
    let stdout = "";
    let stderr = "";
    const timer = setTimeout(() => {
      child.kill("SIGTERM");
      stderr += `\n${script} timed out after ${timeoutMs}ms`;
    }, timeoutMs);
    child.stdout.setEncoding("utf8");
    child.stderr.setEncoding("utf8");
    child.stdout.on("data", (chunk) => {
      stdout += chunk;
    });
    child.stderr.on("data", (chunk) => {
      stderr += chunk;
    });
    child.on("error", (error) => {
      clearTimeout(timer);
      resolveResult({ code: 127, stdout, stderr: `${stderr}${error.message}` });
    });
    child.on("close", (code) => {
      clearTimeout(timer);
      resolveResult({ code: code ?? 1, stdout, stderr });
    });
  });
}

export async function runPythonChecked(script, args = [], options = {}) {
  const result = await runPython(script, args, options);
  if (result.code !== 0) {
    const error = new Error(result.stderr.trim() || `${script} exited with ${result.code}`);
    error.result = result;
    throw error;
  }
  return result;
}

export function runPythonInherit(script, args = []) {
  const proc = spawnSync(pythonCommand(), [assertScript(script), ...args], {
    cwd: packageRoot,
    env: process.env,
    stdio: "inherit"
  });
  return proc.status ?? 1;
}

export function toArgs(values) {
  return values.filter((value) => value !== undefined && value !== null && value !== false);
}
