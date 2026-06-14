import { rankReferences } from "../core/corpus.js";
import { fail, ok } from "./result.js";

export function selectReference(options) {
  const query = String(options.description || "").trim();
  if (!query) return fail(2, "description required\n");
  const ranked = rankReferences(query, { top: Number(options.top || 5) });
  if (options.json) return ok(`${JSON.stringify(ranked, null, 2)}\n`);

  const lines = [`query: ${query}`];
  ranked.forEach((candidate, index) => {
    lines.push(`${index + 1}. ${String(candidate.score.toFixed(1)).padStart(5)}  ${candidate.path}`);
    for (const reason of candidate.reasons.slice(0, 3)) lines.push(`   - ${reason}`);
  });
  return ok(`${lines.join("\n")}\n`);
}
