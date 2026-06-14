import { copyFileSync, existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { referenceExamplesDir } from "../core/paths.js";
import { rankReferences, referencePool } from "../core/corpus.js";
import { fail, ok } from "./result.js";

function findTemplate(name) {
  const direct = resolve(referenceExamplesDir, name);
  if (existsSync(direct)) return direct;
  const target = name.toLowerCase().replace(/\.drawio$/, "");
  for (const path of referencePool()) {
    const file = path.split(/[\\/]/).at(-1).toLowerCase();
    const stem = file.replace(/\.drawio$/, "");
    if (file === target || stem === target) return path;
  }
  return null;
}

function renameDiagram(path, newName) {
  const text = readFileSync(path, "utf8");
  const updated = text.replace(/<diagram\b([^>]*?)\bname="[^"]*"/, `<diagram$1name="${String(newName).replace(/&/g, "&amp;").replace(/"/g, "&quot;")}"`);
  if (updated === text) return false;
  writeFileSync(path, updated, "utf8");
  return true;
}

export function scaffoldDiagram(options) {
  const query = String(options.description || "").trim();
  if (!query && !options.template) return fail(2, "description or --template required\n");
  if (!existsSync(referenceExamplesDir)) return fail(1, `${referenceExamplesDir}: reference directory not found\n`);

  let chosen = null;
  let candidates = [];
  if (options.template) {
    chosen = findTemplate(options.template);
    if (!chosen) return fail(1, `--template '${options.template}': not found in ${referenceExamplesDir}\n`);
  } else {
    candidates = rankReferences(query, { top: Number(options.top || 5) });
    if (!candidates.length) return fail(1, "no candidates found\n");
    chosen = candidates[0].path;
  }

  if (options.dryRun || !options.out) {
    if (options.json) {
      return ok(`${JSON.stringify({ query, chosen, candidates }, null, 2)}\n`);
    }
    const lines = [`query  : ${query}`, `chosen : ${chosen}`];
    if (candidates.length) {
      lines.push(`top ${candidates.length} candidates:`);
      candidates.forEach((candidate, index) => {
        lines.push(`  ${index + 1}. ${String(candidate.score.toFixed(1)).padStart(5)}  ${candidate.path.split(/[\\/]/).at(-1)}`);
        for (const reason of candidate.reasons.slice(0, 2)) lines.push(`     - ${reason}`);
      });
    }
    return ok(`${lines.join("\n")}\n`);
  }

  const dest = resolve(options.out);
  if (existsSync(dest) && !options.force) return fail(1, `${dest}: already exists (use --force to overwrite)\n`);
  mkdirSync(dirname(dest), { recursive: true });
  copyFileSync(chosen, dest);
  const renamed = options.diagramName ? renameDiagram(dest, options.diagramName) : false;
  if (options.json) {
    return ok(`${JSON.stringify({ query, template: chosen, destination: dest, renamed_diagram: renamed, candidates }, null, 2)}\n`);
  }
  const warning = options.diagramName && !renamed ? `warning: --diagram-name '${options.diagramName}' did not match a <diagram> element\n` : "";
  return ok(`scaffolded ${dest} from ${chosen.split(/[\\/]/).at(-1)}\n${warning}`);
}
