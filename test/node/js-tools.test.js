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
import { canonicalizeXml, elementsByTag, parseXml } from "../../src/core/xml.js";

const cli = fileURLToPath(new URL("../../bin/btp-drawio.js", import.meta.url));
const repoRoot = dirname(dirname(dirname(fileURLToPath(import.meta.url))));
const referenceDir = join(repoRoot, "plugins", "sap-architecture", "skills", "sap-architecture", "assets", "reference-examples");
const selectParityPrompts = [
  "Developer uses ARC-1 on SAP BTP Cloud Foundry to call on-premise SAP S/4HANA through Cloud Connector",
  "Private Link connectivity from SAP BTP to a hyperscaler service",
  "SIEM and SOAR integration with SAP Enterprise Threat Detection",
  "Joule agentic AI scenario with tools, grounding, and SAP BTP services",
  "CAP application with SAP Fiori frontend and SAP HANA Cloud database",
  "Event Mesh and Kafka event-driven integration across SAP systems",
  "Hyperscaler data integration to Databricks with SAP Datasphere",
  "CI/CD DevOps pipeline for SAP BTP applications",
  "SAP Cloud Identity Services authentication and authorization landscape",
  "SAP Task Center with SAP Start and workflow inbox integration",
  "SAP Build Process Automation with approval workflows",
  "SAP Build Work Zone launchpad and content federation",
  "Integration Suite exposing APIs for SAP S/4HANA and third-party systems",
  "SAP HANA Cloud multi availability zone architecture",
  "Kyma runtime extension application on SAP BTP",
  "SAP Analytics Cloud planning integration with SAP Datasphere",
  "Mobile services consuming SAP backend APIs through BTP",
  "ABAP environment side-by-side extension on SAP BTP"
];

function run(args, env = {}) {
  return execFileSync("node", [cli, ...args], {
    encoding: "utf8",
    env: { ...process.env, ...env },
    stdio: ["ignore", "pipe", "pipe"]
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

function firstLabeledElementId(xml) {
  for (const elem of elementsByTag(parseXml(xml), "*")) {
    const id = elem.getAttribute("id");
    if (id && (elem.hasAttribute("value") || elem.hasAttribute("label") || elem.hasAttribute("name"))) {
      return id;
    }
  }
  throw new Error("fixture has no labeled element with an id");
}

function decodeXmlMarkupEntities(text) {
  return String(text)
    .replace(/&lt;|&#0*60;|&#x0*3c;/gi, "<")
    .replace(/&gt;|&#0*62;|&#x0*3e;/gi, ">")
    .replace(/&quot;|&#0*34;|&#x0*22;/gi, '"')
    .replace(/&apos;|&#0*39;|&#x0*27;/gi, "'");
}

function normalizeXmlFragmentOutput(xml) {
  const text = String(xml).trim();
  if (text.startsWith("<")) return text;
  const decoded = decodeXmlMarkupEntities(text).trim();
  return decoded.startsWith("<") ? decoded : text;
}

function canonicalizeXmlIgnoringEmbeddedSvgData(xml) {
  const masked = normalizeXmlFragmentOutput(xml).replace(/image=data:image\/svg\+xml,[^;"]+/g, "image=data:image/svg+xml,__IMAGE__");
  const canonical = canonicalizeXml(masked);
  const decodedCanonical = normalizeXmlFragmentOutput(canonical);
  return decodedCanonical === canonical ? canonical : canonicalizeXml(decodedCanonical);
}

function embeddedSvgDataCount(xml) {
  return [...normalizeXmlFragmentOutput(xml).matchAll(/image=data:image\/svg\+xml,([^;"]+)/g)].length;
}

function sortedAttrs(attrs) {
  return Object.fromEntries(Object.entries(attrs).sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0)));
}

function parseAttrs(text = "") {
  const attrs = {};
  for (const match of String(text).matchAll(/\s+([A-Za-z_:][-A-Za-z0-9_:.]*)=(?:"([^"]*)"|'([^']*)')/g)) {
    attrs[match[1]] = match[2] ?? match[3] ?? "";
  }
  return sortedAttrs(attrs);
}

function extractCellFingerprint(xml) {
  const masked = normalizeXmlFragmentOutput(xml).replace(/image=data:image\/svg\+xml,[^;"]+/g, "image=data:image/svg+xml,__IMAGE__");
  const parsed = parseXml(`<__extract_root>${masked}</__extract_root>`);
  const domCells = elementsByTag(parsed, "mxCell");
  if (domCells.length) {
    return domCells.map((cell) => {
      const attrs = {};
      for (let i = 0; i < cell.attributes.length; i += 1) {
        const attr = cell.attributes.item(i);
        attrs[attr.name] = attr.value;
      }
      return {
        attrs: sortedAttrs(attrs),
        geometry: elementsByTag(cell, "mxGeometry").map((geometry) => {
          const geometryAttrs = {};
          for (let i = 0; i < geometry.attributes.length; i += 1) {
            const attr = geometry.attributes.item(i);
            geometryAttrs[attr.name] = attr.value;
          }
          return sortedAttrs(geometryAttrs);
        })
      };
    });
  }

  const normalized = normalizeXmlFragmentOutput(canonicalizeXml(masked));
  return [...normalized.matchAll(/<mxCell\b([^>]*)>([\s\S]*?)<\/mxCell>|<mxCell\b([^>]*)\/>/g)].map((match) => {
    const body = match[2] || "";
    return {
      attrs: parseAttrs(match[1] || match[3] || ""),
      geometry: [...body.matchAll(/<mxGeometry\b([^>]*)\/?>/g)].map((geometry) => parseAttrs(geometry[1]))
    };
  });
}

function assertBuildWorkZoneExtract(xml, label) {
  const text = decodeXmlMarkupEntities(String(xml));
  assert.match(text, /id="wz"/, `${label} id`);
  assert.match(text, /SAP Build Work Zone -(?:&amp;)?#10;Standard Edition/, `${label} label`);
  assert.match(text, /vertex="1"/, `${label} vertex`);
  assert.match(text, /parent="1"/, `${label} parent`);
  assert.match(text, /image=data:image\/svg\+xml,/, `${label} image`);
  assert.match(text, /points=\[\[0,0,0,0,0\]/, `${label} connection points`);
  assert.match(text, /x="0"/, `${label} x`);
  assert.match(text, /y="0"/, `${label} y`);
  assert.match(text, /width="30"/, `${label} width`);
  assert.match(text, /height="30"/, `${label} height`);
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

test("canonicalizeXml compares XML structure instead of serializer whitespace", () => {
  assert.equal(canonicalizeXml('<mxCell b="2" a="1" />'), canonicalizeXml('<mxCell a="1" b="2"/>'));
  assert.equal(canonicalizeXml('<root><child value="A&#10;B" /></root>'), canonicalizeXml('<root><child value="A&#xA;B"/></root>'));
  assert.equal(
    canonicalizeXmlIgnoringEmbeddedSvgData('&lt;mxCell id="a" value="One" /&gt;'),
    canonicalizeXmlIgnoringEmbeddedSvgData('<mxCell value="One" id="a"/>')
  );
  assert.equal(
    canonicalizeXmlIgnoringEmbeddedSvgData('&#60;mxCell id="a" value="One" /&#62;'),
    canonicalizeXmlIgnoringEmbeddedSvgData('<mxCell value="One" id="a"/>')
  );
  assert.notEqual(
    canonicalizeXmlIgnoringEmbeddedSvgData('&lt;mxCell id="a" value="One" /&gt;'),
    canonicalizeXmlIgnoringEmbeddedSvgData('<mxCell value="Two" id="a"/>')
  );
  assert.deepEqual(
    extractCellFingerprint('&lt;mxCell id="a" value="One"&gt;&lt;mxGeometry x="0" as="geometry"/&gt;&lt;/mxCell&gt;'),
    extractCellFingerprint('<mxCell value="One" id="a"><mxGeometry as="geometry" x="0"/></mxCell>')
  );
  assert.notDeepEqual(
    extractCellFingerprint('&lt;mxCell id="a" value="One" /&gt;'),
    extractCellFingerprint('<mxCell value="Two" id="a"/>')
  );
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

test("ported extract tools match Python semantically despite XML serializer whitespace", () => {
  const cases = [
    ["extract-icon", ["Cloud Connector", "--id", "cc", "--x", "12", "--y", "19"]],
    ["extract-icon", ["Build Work Zone", "--id", "wz"]],
    ["extract-asset", ["on-premise-sap", "--kind", "generic-icon", "--id", "backend"]],
    ["extract-asset", ["sap-destination-service", "--kind", "btp-service-icon", "--id", "dest"]]
  ];

  for (const [command, args] of cases) {
    const pyOut = run([command, ...args], { BTP_DRAWIO_ENGINE: "python" });
    const jsOut = run([command, ...args], {
      BTP_DRAWIO_ENGINE: "js",
      BTP_DRAWIO_PYTHON: "definitely-not-python"
    });
    assert.equal(embeddedSvgDataCount(jsOut), embeddedSvgDataCount(pyOut), `${command} ${args.join(" ")} image count`);
    if (command === "extract-icon" && args[0] === "Build Work Zone") {
      assertBuildWorkZoneExtract(jsOut, "js");
      assertBuildWorkZoneExtract(pyOut, "python");
      continue;
    }
    assert.deepEqual(extractCellFingerprint(jsOut), extractCellFingerprint(pyOut), `${command} ${args.join(" ")}`);
  }
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

test("ported relabel matches Python semantically across all bundled references", () => {
  const dir = mkdtempSync(join(tmpdir(), "btp-drawio-js-relabel-corpus-"));
  const files = collectDrawioFiles(referenceDir);
  assert.equal(files.length, 71);

  for (const [index, source] of files.entries()) {
    const fixtureDir = join(dir, String(index));
    mkdirSync(fixtureDir);
    const pyFile = join(fixtureDir, "python.drawio");
    const jsFile = join(fixtureDir, "js.drawio");
    const pyOut = join(fixtureDir, "python-out.drawio");
    const jsOut = join(fixtureDir, "js-out.drawio");
    const mappingFile = join(fixtureDir, "mapping.json");
    const original = readFileSync(source, "utf8");
    const targetId = firstLabeledElementId(original);
    const mapping = { ids: { [targetId]: `Parity Replacement ${index}` } };

    writeFileSync(pyFile, original);
    writeFileSync(jsFile, original);
    writeFileSync(mappingFile, JSON.stringify(mapping));

    run(["relabel", pyFile, mappingFile, "--out", pyOut], { BTP_DRAWIO_ENGINE: "python" });
    const jsRun = spawn(["relabel", jsFile, mappingFile, "--out", jsOut], {
      BTP_DRAWIO_ENGINE: "js",
      BTP_DRAWIO_PYTHON: "definitely-not-python"
    });
    assert.equal(jsRun.status, 0, `${basename(source)}\n${jsRun.stderr}`);
    assert.equal(canonicalizeXml(readFileSync(jsOut, "utf8")), canonicalizeXml(readFileSync(pyOut, "utf8")), basename(source));
  }
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

test("ported select matches Python top candidates and scores across diverse prompts", () => {
  for (const prompt of selectParityPrompts) {
    const pyTop = JSON.parse(run(["select", prompt, "--top", "3", "--json"], { BTP_DRAWIO_ENGINE: "python" }));
    const jsTop = JSON.parse(run(["select", prompt, "--top", "3", "--json"], {
      BTP_DRAWIO_ENGINE: "js",
      BTP_DRAWIO_PYTHON: "definitely-not-python"
    }));
    assert.deepEqual(
      jsTop.map((candidate) => [basename(candidate.path), candidate.score]),
      pyTop.map((candidate) => [basename(candidate.path), candidate.score]),
      prompt
    );
  }
});

test("ported scaffold chooses same template as Python for diverse prompts", () => {
  const dir = mkdtempSync(join(tmpdir(), "btp-drawio-js-scaffold-prompts-"));
  for (const [index, prompt] of selectParityPrompts.entries()) {
    const pyTop = JSON.parse(run(["select", prompt, "--top", "1", "--json"], { BTP_DRAWIO_ENGINE: "python" }))[0];
    const out = join(dir, `scaffold-${index}.drawio`);
    const scaffold = run(["scaffold", prompt, "--out", out, "--json"], {
      BTP_DRAWIO_ENGINE: "js",
      BTP_DRAWIO_PYTHON: "definitely-not-python"
    });
    assert.equal(basename(JSON.parse(scaffold).template), basename(pyTop.path), prompt);
    assert.match(readFileSync(out, "utf8"), /mxfile/);
  }
});

test("ported scaffold output matches Python semantically across all bundled templates", () => {
  const dir = mkdtempSync(join(tmpdir(), "btp-drawio-js-scaffold-corpus-"));
  const files = collectDrawioFiles(referenceDir);
  assert.equal(files.length, 71);

  for (const [index, source] of files.entries()) {
    const fixtureDir = join(dir, String(index));
    mkdirSync(fixtureDir);
    const pyOut = join(fixtureDir, "python.drawio");
    const jsOut = join(fixtureDir, "js.drawio");
    const diagramName = `Scaffold Parity ${index}`;
    const template = basename(source);

    run(["scaffold", "--template", template, "--diagram-name", diagramName, "--out", pyOut, "--json"], {
      BTP_DRAWIO_ENGINE: "python"
    });
    const jsRun = spawn(["scaffold", "--template", template, "--diagram-name", diagramName, "--out", jsOut, "--json"], {
      BTP_DRAWIO_ENGINE: "js",
      BTP_DRAWIO_PYTHON: "definitely-not-python"
    });
    assert.equal(jsRun.status, 0, `${template}\n${jsRun.stderr}`);
    assert.equal(canonicalizeXml(readFileSync(jsOut, "utf8")), canonicalizeXml(readFileSync(pyOut, "utf8")), template);
  }
});
