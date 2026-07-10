#!/usr/bin/env node
import { existsSync } from "node:fs";
import { spawnSync } from "node:child_process";
import { checkPython, missingPythonMessage, packageRoot, runPythonInherit, scriptPath } from "../lib/python-tools.js";
import { JS_COMMANDS, runJsCommand, shouldUseJsEngine } from "../src/cli.js";

const COMMANDS = new Map([
  ["scaffold", "scaffold_diagram.py"],
  ["select", "select_reference.py"],
  ["semantic", "render_semantic.py"],
  ["validate", "validate.py"],
  ["validate-semantics", "validate_semantics.py"],
  ["provenance", "provenance.py"],
  ["verify-delivery", "verify_delivery.py"],
  ["record-visual-review", "record_visual_review.py"],
  ["autofix", "autofix.py"],
  ["score", "score_corpus.py"],
  ["compare", "compare.py"],
  ["render", "render.py"],
  ["render-compare", "render_compare.py"],
  ["template-browser", "template_browser.py"],
  ["extract-icon", "extract_icon.py"],
  ["extract-asset", "extract_asset.py"],
  ["relabel", "relabel.py"],
  ["find-pattern", "find_pattern.py"]
]);

function usage() {
  console.log(`btp-drawio

Node/npx wrapper for the SAP BTP draw.io skill.

Usage:
  btp-drawio doctor
  btp-drawio scaffold "<request>" --out diagram.drawio
  btp-drawio semantic "<request>" --out diagram.drawio
  btp-drawio validate diagram.drawio
  btp-drawio validate-semantics diagram.drawio diagram.spec.json
  btp-drawio verify-delivery diagram.drawio diagram.spec.json --target template.drawio --out-dir .cache/review
  btp-drawio score --min-score 90 diagram.drawio
  btp-drawio render diagram.drawio -o diagram.png
  btp-drawio extract-icon "Destination Service" --id dest
  btp-drawio mcp

Commands:
  scaffold          Copy the closest SAP reference template.
  semantic          Render a deterministic semantic fallback diagram.
  validate          Run structural/style validation.
  validate-semantics  Validate required nodes, terms, and directed flows.
  provenance        Mark/audit derivative provenance and source identifiers.
  verify-delivery   Run the guarded final delivery gate.
  record-visual-review  Record a hash-bound rendered-image review.
  autofix           Apply mechanical fixes.
  score             Score against the bundled corpus.
  compare           Compare two .drawio files.
  render            Export via draw.io desktop CLI.
  render-compare    Build side-by-side visual review HTML.
  template-browser  Render the bundled template gallery.
  extract-icon      Emit a BTP service icon mxCell.
  extract-asset     Emit any indexed SAP starter-kit asset.
  relabel           Apply deterministic id/visible-label map.
  find-pattern      Search the template profile registry.
  select            Rank templates for a prompt.
  doctor            Check local runtimes.
  mcp               Start stdio MCP server.

Environment:
  BTP_DRAWIO_PYTHON  Python command to use (default: python3)
  DRAWIO_CLI         Optional draw.io desktop CLI path
`);
}

function printDoctor() {
  let ok = true;
  console.log(`package root: ${packageRoot}`);

  const python = checkPython();
  if (python) {
    console.log(`python      : ${python.command} (${python.version})`);
  } else {
    ok = false;
    console.log(`python      : missing (${missingPythonMessage()})`);
  }

  for (const script of [
    "scaffold_diagram.py",
    "render_semantic.py",
    "validate.py",
    "validate_semantics.py",
    "provenance.py",
    "verify_delivery.py",
    "record_visual_review.py",
    "score_corpus.py"
  ]) {
    const path = scriptPath(script);
    console.log(`${script.padEnd(25)}: ${existsSync(path) ? "ok" : "missing"}`);
    if (!existsSync(path)) ok = false;
  }

  const macDrawio = "/Applications/draw.io.app/Contents/MacOS/draw.io";
  const drawioCommand = process.env.DRAWIO_CLI || (existsSync(macDrawio) ? macDrawio : "drawio");
  const drawioProbe = spawnSync(drawioCommand, ["--version"], {
    encoding: "utf8",
    stdio: ["ignore", "pipe", "pipe"]
  });
  if (drawioProbe.status === 0) {
    console.log(`draw.io CLI : ${(drawioProbe.stdout || drawioProbe.stderr).trim() || "ok"}`);
  } else {
    ok = false;
    console.log("draw.io CLI : missing (guarded completion requires rendering; install draw.io or set DRAWIO_CLI)");
  }

  return ok ? 0 : 1;
}

const [, , command, ...args] = process.argv;

if (!command || command === "-h" || command === "--help") {
  usage();
  process.exit(0);
}

if (command === "doctor") {
  process.exit(printDoctor());
}

if (command === "mcp") {
  const { main } = await import("./btp-drawio-mcp.js");
  await main();
  await new Promise(() => {});
}

const script = COMMANDS.get(command);
if (!script) {
  console.error(`unknown command: ${command}\n`);
  usage();
  process.exit(2);
}

if (shouldUseJsEngine(command)) {
  if (!JS_COMMANDS.has(command)) {
    console.error(`command ${command} is not available in the JS engine yet; use BTP_DRAWIO_ENGINE=python`);
    process.exit(2);
  }
  const result = await runJsCommand(command, args);
  if (result.stdout) process.stdout.write(result.stdout);
  if (result.stderr) process.stderr.write(result.stderr);
  process.exit(result.code);
}

process.exit(runPythonInherit(script, args));
