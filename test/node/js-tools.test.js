import { execFileSync, spawnSync } from "node:child_process";
import { mkdtempSync, readFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { basename, join } from "node:path";
import test from "node:test";
import assert from "node:assert/strict";
import { pyRound } from "../../src/core/round.js";

const cli = new URL("../../bin/btp-drawio.js", import.meta.url).pathname;

function run(args, env = {}) {
  return execFileSync("node", [cli, ...args], {
    encoding: "utf8",
    env: { ...process.env, ...env }
  });
}

function spawn(args, env = {}) {
  return spawnSync("node", [cli, ...args], {
    encoding: "utf8",
    env: { ...process.env, ...env }
  });
}

test("pyRound matches Python half-even rounding traps", () => {
  assert.equal(pyRound(2.5), 2);
  assert.equal(pyRound(3.5), 4);
  assert.equal(pyRound(0.05, 1), 0);
  assert.equal(pyRound(0.15, 1), 0.2);
  assert.equal(pyRound(1.25, 1), 1.2);
});

test("ported extract tools run without Python and keep icon guard behavior", () => {
  const env = { BTP_DRAWIO_ENGINE: "js", BTP_DRAWIO_PYTHON: "definitely-not-python" };
  const rejected = spawn(["extract-icon", "SAP S/4HANA"], env);
  assert.equal(rejected.status, 1);
  assert.match(rejected.stderr, /backend system\/product label/);
  assert.doesNotMatch(rejected.stderr, /Microsoft Teams/);

  const asset = run(["extract-asset", "on-premise-sap", "--kind", "generic-icon", "--id", "backend"], env);
  assert.match(asset, /id="backend"/);
  assert.match(asset, /On Premise SAP/);

  const workZone = run(["extract-icon", "Build Work Zone", "--id", "wz"], env);
  assert.match(workZone, /SAP Build Work Zone/);
  assert.match(workZone, /Standard Edition/);
});

test("ported relabel supports inline JSON and preserves drawio output validity", () => {
  const dir = mkdtempSync(join(tmpdir(), "btp-drawio-js-relabel-"));
  const source = join(dir, "source.drawio");
  const out = join(dir, "out.drawio");
  run([
    "semantic",
    "Developer uses ARC-1 on SAP BTP Cloud Foundry to call on-premise SAP S/4HANA through Cloud Connector",
    "--out",
    source
  ], { BTP_DRAWIO_ENGINE: "python" });

  const relabel = spawn([
    "relabel",
    source,
    "--mapping-json",
    JSON.stringify({ "SAP Cloud Connector": "Customer Cloud Connector" }),
    "--out",
    out
  ], { BTP_DRAWIO_ENGINE: "js", BTP_DRAWIO_PYTHON: "definitely-not-python" });
  assert.equal(relabel.status, 0, relabel.stderr);
  assert.match(relabel.stderr, /replaced 1 label/);
  assert.match(readFileSync(out, "utf8"), /Customer Cloud Connector/);

  const validate = run(["validate", out], { BTP_DRAWIO_ENGINE: "python" });
  assert.match(validate, /OK/);
});

test("ported select/scaffold choose the same top template as Python oracle", () => {
  const prompt = "Developer uses ARC-1 on SAP BTP Cloud Foundry to call on-premise SAP S/4HANA through Cloud Connector";
  const pyTop = JSON.parse(run(["select", prompt, "--top", "1", "--json"], { BTP_DRAWIO_ENGINE: "python" }))[0];
  const jsTop = JSON.parse(run(["select", prompt, "--top", "1", "--json"], { BTP_DRAWIO_ENGINE: "js", BTP_DRAWIO_PYTHON: "definitely-not-python" }))[0];
  assert.equal(basename(jsTop.path), basename(pyTop.path));

  const dir = mkdtempSync(join(tmpdir(), "btp-drawio-js-scaffold-"));
  const out = join(dir, "scaffold.drawio");
  const scaffold = run(["scaffold", prompt, "--out", out, "--json"], { BTP_DRAWIO_ENGINE: "js", BTP_DRAWIO_PYTHON: "definitely-not-python" });
  assert.equal(basename(JSON.parse(scaffold).template), basename(pyTop.path));
  assert.match(readFileSync(out, "utf8"), /mxfile/);
});
