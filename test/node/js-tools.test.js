import { execFileSync, spawnSync } from "node:child_process";
import { mkdtempSync, mkdirSync, readFileSync, readdirSync, statSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { basename, dirname, join } from "node:path";
import test from "node:test";
import assert from "node:assert/strict";
import { fileURLToPath } from "node:url";
import { resolvedPythonCommand } from "../../lib/python-tools.js";
import { pyRound, snap10 } from "../../src/core/round.js";
import { parseCompareStyle, parseValidateStyle } from "../../src/core/styles.js";

const cli = new URL("../../bin/btp-drawio.js", import.meta.url).pathname;
const repoRoot = dirname(dirname(dirname(fileURLToPath(import.meta.url))));
const referenceDir = join(repoRoot, "plugins", "sap-architecture", "skills", "sap-architecture", "assets", "reference-examples");

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

function collectDrawioFiles(dir) {
  const out = [];
  for (const entry of readdirSync(dir)) {
    const path = join(dir, entry);
    if (statSync(path).isDirectory()) out.push(...collectDrawioFiles(path));
    else if (entry.endsWith(".drawio")) out.push(path);
  }
  return out.sort();
}

test("pyRound matches Python half-even rounding traps", () => {
  assert.equal(pyRound(2.5), 2);
  assert.equal(pyRound(3.5), 4);
  assert.equal(pyRound(0.05, 1), 0);
  assert.equal(pyRound(0.15, 1), 0.2);
  assert.equal(pyRound(1.25, 1), 1.2);
  assert.equal(pyRound(-13.49999999999999), -13);
  assert.equal(pyRound(-13.5), -14);
  assert.equal(snap10(-134.9999999999999), -130);
  assert.equal(snap10(-135), -140);
});

test("style parser matches both Python parsers across bundled references", () => {
  const styles = [
    ...new Set(
      collectDrawioFiles(referenceDir).flatMap((file) =>
        [...readFileSync(file, "utf8").matchAll(/style="([^"]*)"/g)].map((match) => match[1])
      )
    )
  ].sort();
  assert.ok(styles.length > 100);

  const python = resolvedPythonCommand();
  assert.ok(python, "Python oracle is required for style parser parity during migration");
  const oracle = JSON.parse(
    execFileSync(
      python,
      [
        "-c",
        [
          "import json, sys",
          "sys.path.insert(0, 'plugins/sap-architecture/skills/sap-architecture/scripts')",
          "import compare, validate",
          "styles = json.load(sys.stdin)",
          "print(json.dumps({'validate': [validate.parse_style(s) for s in styles], 'compare': [compare.parse_style_dict(s) for s in styles]}))"
        ].join("; ")
      ],
      { cwd: repoRoot, input: JSON.stringify(styles), encoding: "utf8", maxBuffer: 32 * 1024 * 1024 }
    )
  );

  assert.deepEqual(styles.map((style) => parseValidateStyle(style)), oracle.validate);
  assert.deepEqual(styles.map((style) => parseCompareStyle(style)), oracle.compare);
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

test("ported autofix matches Python output and runs without Python", () => {
  const dir = mkdtempSync(join(tmpdir(), "btp-drawio-js-autofix-"));
  const pyFile = join(dir, "python.drawio");
  const jsFile = join(dir, "js.drawio");
  const dirty = `<mxfile><diagram name="x"><mxGraphModel><root><mxCell id="0"/><mxCell id="1" parent="0"/><!-- remove --><mxCell id="2" value="Box" style="rounded=1;arcSize=12;strokeColor=#abcdef;strokeWidth=1.2;fontFamily=Arial;" vertex="1" parent="1"><mxGeometry x="12" y="19" width="101.5" height="39.9" as="geometry"/></mxCell></root></mxGraphModel></diagram></mxfile>`;
  writeFileSync(pyFile, dirty);
  writeFileSync(jsFile, dirty);

  run(["autofix", pyFile, "--write"], { BTP_DRAWIO_ENGINE: "python" });
  const jsRun = spawn(["autofix", jsFile, "--write"], {
    BTP_DRAWIO_ENGINE: "js",
    BTP_DRAWIO_PYTHON: "definitely-not-python"
  });
  assert.equal(jsRun.status, 0, jsRun.stderr);
  assert.equal(readFileSync(jsFile, "utf8"), readFileSync(pyFile, "utf8"));
  assert.match(readFileSync(jsFile, "utf8"), /strokeColor=#ABCDEF/);
  assert.match(readFileSync(jsFile, "utf8"), /absoluteArcSize=1/);
  assert.doesNotMatch(readFileSync(jsFile, "utf8"), /<!-- remove -->/);

  const secondRun = run(["autofix", jsFile], {
    BTP_DRAWIO_ENGINE: "js",
    BTP_DRAWIO_PYTHON: "definitely-not-python"
  });
  assert.match(secondRun, /no fixes needed/);
});

test("ported autofix matches Python across all bundled references", () => {
  const dir = mkdtempSync(join(tmpdir(), "btp-drawio-js-autofix-corpus-"));
  const files = collectDrawioFiles(referenceDir);
  assert.equal(files.length, 71);

  for (const [index, source] of files.entries()) {
    const fixtureDir = join(dir, String(index));
    mkdirSync(fixtureDir);
    const pyFile = join(fixtureDir, "python.drawio");
    const jsFile = join(fixtureDir, "js.drawio");
    const original = readFileSync(source, "utf8");
    writeFileSync(pyFile, original);
    writeFileSync(jsFile, original);

    run(["autofix", pyFile, "--write"], { BTP_DRAWIO_ENGINE: "python" });
    const jsRun = spawn(["autofix", jsFile, "--write"], {
      BTP_DRAWIO_ENGINE: "js",
      BTP_DRAWIO_PYTHON: "definitely-not-python"
    });
    assert.equal(jsRun.status, 0, `${basename(source)}\n${jsRun.stderr}`);
    assert.equal(readFileSync(jsFile, "utf8"), readFileSync(pyFile, "utf8"), basename(source));
  }
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
