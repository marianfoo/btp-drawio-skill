#!/usr/bin/env node
import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import { fileURLToPath } from "node:url";
import { z } from "zod";
import { checkPython, packageRoot, runPython, toArgs } from "../lib/python-tools.js";

const diagramPath = z.string().min(1).describe("Local .drawio path");

function textResult(result) {
  const text = [result.stdout.trim(), result.stderr.trim()].filter(Boolean).join("\n");
  return {
    content: [{ type: "text", text: text || `exit code ${result.code}` }],
    isError: result.code !== 0
  };
}

async function runTool(script, args, timeoutMs = 120_000) {
  const result = await runPython(script, args, { timeoutMs });
  return textResult(result);
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
      runTool(
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
      description: "Validate a .drawio file for SAP style and structural issues.",
      inputSchema: {
        file: diagramPath,
        strict: z.boolean().optional(),
        json: z.boolean().optional()
      }
    },
    async ({ file, strict, json }) => runTool("validate.py", toArgs([file, strict ? "--strict" : undefined, json ? "--json" : undefined]))
  );

  server.registerTool(
    "btp_drawio_score",
    {
      description: "Score a .drawio file against the bundled SAP reference corpus.",
      inputSchema: {
        file: diagramPath,
        minScore: z.number().optional(),
        minSapLike: z.number().optional(),
        top: z.number().int().positive().optional(),
        json: z.boolean().optional(),
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
          json ? "--json" : undefined,
          scoreOnly ? "--score" : undefined,
          sapScoreOnly ? "--sap-score" : undefined,
          file
        ])
      )
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
      description: "Apply deterministic label replacements to a scaffolded .drawio file.",
      inputSchema: {
        file: diagramPath,
        mapping: z.string().min(1).describe("JSON label map path"),
        out: diagramPath.optional(),
        write: z.boolean().optional()
      }
    },
    async ({ file, mapping, out, write }) => runTool("relabel.py", toArgs([file, mapping, out ? "--out" : undefined, out, write ? "--write" : undefined]))
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
      runTool(
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

  const transport = new StdioServerTransport();
  await server.connect(transport);
}

if (process.argv[1] && fileURLToPath(import.meta.url) === process.argv[1]) {
  main().catch((error) => {
    console.error(error);
    process.exit(1);
  });
}
