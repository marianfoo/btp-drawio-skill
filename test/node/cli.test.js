import { execFileSync } from "node:child_process";
import { mkdtempSync, readFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";
import assert from "node:assert/strict";
import { fileURLToPath } from "node:url";

const cli = fileURLToPath(new URL("../../bin/btp-drawio.js", import.meta.url));

function run(args) {
  return execFileSync("node", [cli, ...args], {
    encoding: "utf8",
    env: process.env
  });
}

test("doctor reports Python and bundled scripts", () => {
  const out = run(["doctor"]);
  assert.match(out, /python\s+:/);
  assert.match(out, /validate\.py\s+: ok/);
});

test("semantic command creates a valid drawio file", () => {
  const dir = mkdtempSync(join(tmpdir(), "btp-drawio-node-"));
  const out = join(dir, "on-prem.drawio");
  const renderOut = run([
    "semantic",
    "Developer uses ARC-1 on SAP BTP Cloud Foundry to call on-premise SAP S/4HANA through Cloud Connector",
    "--out",
    out,
    "--json"
  ]);
  assert.match(renderOut, /"archetype": "on-prem-connectivity"/);
  assert.match(readFileSync(out, "utf8"), /SAP Cloud&lt;br&gt;Connector/);

  const validateOut = run(["validate", out]);
  assert.match(validateOut, /OK/);
});

test("score command exposes reference-free SAP-likeness score", () => {
  const dir = mkdtempSync(join(tmpdir(), "btp-drawio-node-score-"));
  const out = join(dir, "app.drawio");
  run(["semantic", "CAP application with SAP HANA Cloud and SAP Fiori frontend", "--out", out]);
  const score = run(["score", "--sap-score", out]).trim();
  assert.match(score, /^\d+\.\d$/);
  assert.ok(Number(score) >= 90);
});
