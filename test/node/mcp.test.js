import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { StdioClientTransport } from "@modelcontextprotocol/sdk/client/stdio.js";
import assert from "node:assert/strict";
import { mkdtempSync, readFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

const repoRoot = dirname(dirname(dirname(fileURLToPath(import.meta.url))));
const serverPath = join(repoRoot, "bin", "btp-drawio-mcp.js");

async function withClient(callback) {
  const transport = new StdioClientTransport({
    command: "node",
    args: [serverPath],
    cwd: repoRoot,
    stderr: "pipe"
  });
  const client = new Client({ name: "btp-drawio-mcp-test", version: "0.0.0" });
  try {
    await client.connect(transport);
    return await callback(client);
  } finally {
    await client.close();
  }
}

function textContent(result) {
  return result.content.map((item) => item.text || "").join("\n");
}

test("mcp server exposes complete user-facing tool surface", async () => {
  await withClient(async (client) => {
    const { tools } = await client.listTools();
    const names = tools.map((tool) => tool.name).sort();
    assert.deepEqual(names, [
      "btp_drawio_autofix",
      "btp_drawio_doctor",
      "btp_drawio_extract_asset",
      "btp_drawio_extract_icon",
      "btp_drawio_relabel",
      "btp_drawio_render",
      "btp_drawio_render_semantic",
      "btp_drawio_scaffold",
      "btp_drawio_score",
      "btp_drawio_validate"
    ]);
  });
});

test("mcp tools support inline relabel JSON, asset extraction, autofix, and JSON validation output", async () => {
  await withClient(async (client) => {
    const dir = mkdtempSync(join(tmpdir(), "btp-drawio-mcp-"));
    const source = join(dir, "source.drawio");
    const relabeled = join(dir, "relabeled.drawio");

    const semantic = await client.callTool({
      name: "btp_drawio_render_semantic",
      arguments: {
        request: "Developer uses ARC-1 on SAP BTP Cloud Foundry to call on-premise SAP S/4HANA through Cloud Connector",
        out: source,
        json: true
      }
    });
    assert.equal(semantic.isError, false);

    const validate = await client.callTool({
      name: "btp_drawio_validate",
      arguments: { file: source }
    });
    assert.equal(validate.isError, false);
    assert.equal(JSON.parse(textContent(validate))[0].ok, true);

    const score = await client.callTool({
      name: "btp_drawio_score",
      arguments: { file: source, top: 1 }
    });
    assert.equal(score.isError, false);
    assert.ok(JSON.parse(textContent(score)).sap_likeness.score >= 90);

    const relabel = await client.callTool({
      name: "btp_drawio_relabel",
      arguments: {
        file: source,
        mappingJson: JSON.stringify({ "SAP Cloud Connector": "Customer Cloud Connector" }),
        out: relabeled
      }
    });
    assert.equal(relabel.isError, false);
    assert.match(readFileSync(relabeled, "utf8"), /Customer Cloud Connector/);

    const asset = await client.callTool({
      name: "btp_drawio_extract_asset",
      arguments: {
        query: "on-premise-sap",
        kind: "generic-icon",
        id: "backend"
      }
    });
    assert.equal(asset.isError, false);
    assert.match(textContent(asset), /On Premise SAP/);

    const autofix = await client.callTool({
      name: "btp_drawio_autofix",
      arguments: { file: source }
    });
    assert.equal(autofix.isError, false);
    assert.match(textContent(autofix), /no fixes needed|would fix/);
  });
});
