#!/usr/bin/env node
import { cpSync, existsSync, mkdirSync, readdirSync, rmSync, statSync } from "node:fs";
import { join } from "node:path";
import { spawnSync } from "node:child_process";

const root = process.cwd();
const stage = join(root, ".cache", "mcpb", "btp-drawio-skill");

rmSync(stage, { recursive: true, force: true });
mkdirSync(stage, { recursive: true });

for (const item of ["bin", "lib", "plugins", "package.json", "package-lock.json", "README.md", "LICENSE"]) {
  const source = join(root, item);
  if (existsSync(source)) {
    cpSync(source, join(stage, item), { recursive: true });
  }
}

cpSync(join(root, "mcpb", "manifest.json"), join(stage, "manifest.json"));

function removeGeneratedCaches(dir) {
  if (!existsSync(dir)) return;
  for (const entry of readdirSync(dir)) {
    const path = join(dir, entry);
    const stat = statSync(path);
    if (stat.isDirectory()) {
      if (entry === ".cache" || entry === "__pycache__") {
        rmSync(path, { recursive: true, force: true });
      } else {
        removeGeneratedCaches(path);
      }
    } else if (entry.endsWith(".pyc")) {
      rmSync(path, { force: true });
    }
  }
}

removeGeneratedCaches(join(stage, "plugins"));

const install = spawnSync("npm", ["install", "--omit=dev", "--ignore-scripts"], {
  cwd: stage,
  stdio: "inherit"
});
if (install.status !== 0) {
  process.exit(install.status ?? 1);
}

console.log(`staged MCPB bundle at ${stage}`);
