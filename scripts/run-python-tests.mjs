#!/usr/bin/env node
import { spawnSync } from "node:child_process";
import { missingPythonMessage, resolvedPythonCommand } from "../lib/python-tools.js";

const python = resolvedPythonCommand();
if (!python) {
  console.error(missingPythonMessage());
  process.exit(127);
}

const proc = spawnSync(python, ["-m", "unittest", "discover", "-s", "tests", "-v"], {
  cwd: process.cwd(),
  env: process.env,
  stdio: "inherit"
});

process.exit(proc.status ?? 1);
