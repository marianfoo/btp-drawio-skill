#!/usr/bin/env node
import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import { mkdtemp, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import { z } from "zod";
import { checkPython, missingPythonMessage, packageRoot, runPython, toArgs } from "../lib/python-tools.js";
import { runJsCommand, shouldUseJsEngine } from "../src/cli.js";

const diagramPath = z.string().min(1).describe("Local .drawio path");
const assetKind = z
  .enum([
    "annotation-interface",
    "area-shape",
    "btp-service-icon",
    "connector",
    "default-shape",
    "essential-shape",
    "generic-icon",
    "number-marker",
    "sap-brand-name",
    "text-element"
  ])
  .optional();

function textResult(result) {
  const text = [result.stdout.trim(), result.stderr.trim()].filter(Boolean).join("\n");
  return {
    content: [{ type: "text", text: text || `exit code ${result.code}` }],
    isError: result.code !== 0
  };
}

function errorResult(text) {
  return {
    content: [{ type: "text", text }],
    isError: true
  };
}

async function runTool(script, args, timeoutMs = 120_000) {
  const result = await runPython(script, args, { timeoutMs });
  return textResult(result);
}

async function runEngineTool(command, script, args, timeoutMs = 120_000) {
  if (shouldUseJsEngine(command)) {
    return textResult(await runJsCommand(command, args));
  }
  return runTool(script, args, timeoutMs);
}

async function withRelabelMapping({ mapping, mappingJson }, callback) {
  if (!mapping && !mappingJson) {
    return errorResult("Pass either mapping (path or inline JSON object string) or mappingJson.");
  }
  if (mapping && mappingJson) {
    return errorResult("Pass either mapping or mappingJson, not both.");
  }

  const inline = mappingJson || (mapping?.trim().startsWith("{") ? mapping : null);
  if (!inline) {
    return callback(mapping);
  }

  try {
    JSON.parse(inline);
  } catch (error) {
    return errorResult(`Inline relabel mapping is not valid JSON: ${error.message}`);
  }

  const dir = await mkdtemp(join(tmpdir(), "btp-drawio-relabel-"));
  const path = join(dir, "mapping.json");
  try {
    await writeFile(path, inline, "utf8");
    return await callback(path);
  } finally {
    await rm(dir, { recursive: true, force: true });
  }
}

export async function main() {
  const server = new McpServer({
    name: "btp-drawio-skill",
    version: "0.1.0"
  });

  server.registerTool(
    "btp_drawio_doctor",
    {
      description: "Check local runtime setup for the BTP draw.io skill.",
      inputSchema: {}
    },
    async () => {
      const python = checkPython();
      return {
        content: [
          {
            type: "text",
            text: JSON.stringify(
              {
                packageRoot,
                python: python || null,
                pythonError: python ? null : missingPythonMessage(),
                drawioCli: process.env.DRAWIO_CLI || null
              },
              null,
              2
            )
          }
        ]
      };
    }
  );

  server.registerTool(
    "btp_drawio_scaffold",
    {
      description: "Copy the closest bundled SAP reference template to a destination .drawio file.",
      inputSchema: {
        request: z.string().min(1),
        out: diagramPath.optional(),
        template: z.string().optional(),
        diagramName: z.string().optional(),
        dryRun: z.boolean().optional(),
        json: z.boolean().optional()
      }
    },
    async ({ request, out, template, diagramName, dryRun, json }) =>
      runEngineTool(
        "scaffold",
        "scaffold_diagram.py",
        toArgs([
          request,
          out ? "--out" : undefined,
          out,
          template ? "--template" : undefined,
          template,
          diagramName ? "--diagram-name" : undefined,
          diagramName,
          dryRun ? "--dry-run" : undefined,
          json ? "--json" : undefined
        ])
      )
  );

  server.registerTool(
    "btp_drawio_render_semantic",
    {
      description: "Render a deterministic SAP-style semantic fallback diagram.",
      inputSchema: {
        request: z.string().min(1),
        out: diagramPath,
        archetype: z
          .enum([
            "security-operations",
            "devops",
            "on-prem-connectivity",
            "private-connectivity",
            "btp-application",
            "data-integration",
            "integration-flow",
            "ai-agent",
            "generic-btp"
          ])
          .optional(),
        json: z.boolean().optional()
      }
    },
    async ({ request, out, archetype, json }) =>
      runTool(
        "render_semantic.py",
        toArgs([request, "--out", out, archetype ? "--archetype" : undefined, archetype, json ? "--json" : undefined])
      )
  );

  server.registerTool(
    "btp_drawio_validate",
    {
      description: "Validate a .drawio file for SAP style and structural issues. Returns JSON by default for MCP clients.",
      inputSchema: {
        file: diagramPath,
        strict: z.boolean().optional(),
        json: z.boolean().optional().describe("Defaults to true for MCP calls.")
      }
    },
    async ({ file, strict, json }) =>
      runTool("validate.py", toArgs([file, strict ? "--strict" : undefined, (json ?? true) ? "--json" : undefined]))
  );

  server.registerTool(
    "btp_drawio_score",
    {
      description: "Score a .drawio file against the bundled SAP reference corpus. Returns JSON by default for MCP clients.",
      inputSchema: {
        file: diagramPath,
        minScore: z.number().optional(),
        minSapLike: z.number().optional(),
        top: z.number().int().positive().optional(),
        json: z.boolean().optional().describe("Defaults to true for MCP calls unless scoreOnly or sapScoreOnly is set."),
        scoreOnly: z.boolean().optional(),
        sapScoreOnly: z.boolean().optional()
      }
    },
    async ({ file, minScore, minSapLike, top, json, scoreOnly, sapScoreOnly }) =>
      runTool(
        "score_corpus.py",
        toArgs([
          top ? "--top" : undefined,
          top?.toString(),
          minScore !== undefined ? "--min-score" : undefined,
          minScore?.toString(),
          minSapLike !== undefined ? "--min-sap-like" : undefined,
          minSapLike?.toString(),
          (json ?? !(scoreOnly || sapScoreOnly)) ? "--json" : undefined,
          scoreOnly ? "--score" : undefined,
          sapScoreOnly ? "--sap-score" : undefined,
          file
        ])
      )
  );

  server.registerTool(
    "btp_drawio_autofix",
    {
      description: "Apply deterministic mechanical fixes to a .drawio file, or preview them without writing.",
      inputSchema: {
        file: diagramPath,
        write: z.boolean().optional().describe("Modify the file in place and create a .bak backup.")
      }
    },
    async ({ file, write }) => runEngineTool("autofix", "autofix.py", toArgs([file, write ? "--write" : undefined]))
  );

  server.registerTool(
    "btp_drawio_render",
    {
      description: "Export a .drawio file to PNG, SVG, PDF, or JPG using the draw.io desktop CLI.",
      inputSchema: {
        file: diagramPath,
        output: z.string().optional(),
        format: z.enum(["png", "svg", "pdf", "jpg"]).optional(),
        scale: z.number().positive().optional(),
        border: z.number().int().nonnegative().optional()
      }
    },
    async ({ file, output, format, scale, border }) =>
      runTool(
        "render.py",
        toArgs([
          file,
          output ? "--output" : undefined,
          output,
          format ? "--format" : undefined,
          format,
          scale ? "--scale" : undefined,
          scale?.toString(),
          border !== undefined ? "--border" : undefined,
          border?.toString()
        ]),
        180_000
      )
  );

  server.registerTool(
    "btp_drawio_relabel",
    {
      description: "Apply deterministic label replacements to a scaffolded .drawio file. Accepts a mapping path or inline JSON.",
      inputSchema: {
        file: diagramPath,
        mapping: z.string().optional().describe("JSON label map path, or an inline JSON object string."),
        mappingJson: z.string().optional().describe("Inline JSON label map string."),
        out: diagramPath.optional(),
        write: z.boolean().optional()
      }
    },
    async ({ file, mapping, mappingJson, out, write }) =>
      shouldUseJsEngine("relabel")
        ? textResult(
            await runJsCommand(
              "relabel",
              toArgs([
                file,
                mapping && !mapping.trim().startsWith("{") ? mapping : undefined,
                mapping?.trim().startsWith("{") ? "--mapping-json" : undefined,
                mapping?.trim().startsWith("{") ? mapping : undefined,
                mappingJson ? "--mapping-json" : undefined,
                mappingJson,
                out ? "--out" : undefined,
                out,
                write ? "--write" : undefined
              ])
            )
          )
        : withRelabelMapping({ mapping, mappingJson }, (mappingPath) =>
            runTool("relabel.py", toArgs([file, mappingPath, out ? "--out" : undefined, out, write ? "--write" : undefined]))
          )
  );

  server.registerTool(
    "btp_drawio_extract_icon",
    {
      description: "Emit a ready-to-paste mxCell for a SAP BTP service icon.",
      inputSchema: {
        query: z.string().min(1),
        id: z.string().optional(),
        x: z.number().int().optional(),
        y: z.number().int().optional(),
        w: z.number().int().optional(),
        h: z.number().int().optional(),
        parent: z.string().optional(),
        label: z.string().optional()
      }
    },
    async ({ query, id, x, y, w, h, parent, label }) =>
      runEngineTool(
        "extract-icon",
        "extract_icon.py",
        toArgs([
          query,
          id ? "--id" : undefined,
          id,
          x !== undefined ? "--x" : undefined,
          x?.toString(),
          y !== undefined ? "--y" : undefined,
          y?.toString(),
          w !== undefined ? "--w" : undefined,
          w?.toString(),
          h !== undefined ? "--h" : undefined,
          h?.toString(),
          parent ? "--parent" : undefined,
          parent,
          label ? "--label" : undefined,
          label
        ])
      )
  );

  server.registerTool(
    "btp_drawio_extract_asset",
    {
      description: "Emit a ready-to-paste mxCell for any indexed SAP starter-kit asset, including generic on-premise backend icons.",
      inputSchema: {
        query: z.string().min(1).optional(),
        list: z.boolean().optional(),
        kind: assetKind,
        id: z.string().optional(),
        x: z.number().int().optional(),
        y: z.number().int().optional(),
        w: z.number().int().optional(),
        h: z.number().int().optional(),
        parent: z.string().optional(),
        label: z.string().optional()
      }
    },
    async ({ query, list, kind, id, x, y, w, h, parent, label }) =>
      runEngineTool(
        "extract-asset",
        "extract_asset.py",
        toArgs([
          query,
          list ? "--list" : undefined,
          kind ? "--kind" : undefined,
          kind,
          id ? "--id" : undefined,
          id,
          x !== undefined ? "--x" : undefined,
          x?.toString(),
          y !== undefined ? "--y" : undefined,
          y?.toString(),
          w !== undefined ? "--w" : undefined,
          w?.toString(),
          h !== undefined ? "--h" : undefined,
          h?.toString(),
          parent ? "--parent" : undefined,
          parent,
          label ? "--label" : undefined,
          label
        ])
      )
  );

  const transport = new StdioServerTransport();
  await server.connect(transport);
}

if (process.argv[1] && fileURLToPath(import.meta.url) === process.argv[1]) {
  main().catch((error) => {
    console.error(error);
    process.exit(1);
  });
}
