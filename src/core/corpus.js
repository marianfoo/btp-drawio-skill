import { existsSync, readFileSync, readdirSync } from "node:fs";
import { join } from "node:path";
import { decodeHTML } from "entities";
import { referenceExamplesDir } from "./paths.js";
import { splitWords } from "./labels.js";
import { parseXml, elementsByTag } from "./xml.js";
import { pyRound } from "./round.js";

export const STOPWORDS = new Set([
  "a", "an", "and", "app", "apps", "arch", "architecture", "as", "at", "between",
  "btp", "by", "cloud", "create", "diagram", "draw", "for", "from", "in",
  "into", "is", "l0", "l1", "l2", "landscape", "make", "my", "of", "on", "or",
  "ref", "reference", "sap", "show", "solution", "the", "to", "using",
  "via", "with", "center", "convention", "conventions", "horizon", "icon", "icons",
  "label", "labels", "palette", "preserve", "readable", "rhythm", "semantic",
  "semantics", "style", "template", "visual", "zone", "zones"
]);

export const TOKEN_CANONICAL = {
  adminstrator: "administrator",
  admin: "administrator",
  plaforms: "platforms",
  provisoning: "provisioning",
  ressources: "resources",
  s: "s4hana",
  "4hana": "s4hana"
};

export const SCENARIOS = [
  { name: "identity-authentication", query: ["ias", "identity", "authentication", "authn", "oauth", "oidc", "saml", "single", "sign", "sso", "xsuaa", "jwt", "trust"], reference: ["identity", "authentication", "authn", "iam", "xsuaa", "ias", "joule_iam"], boost: 18 },
  { name: "identity-authorization", query: ["authorization", "authz", "role", "roles", "scope", "scopes", "permission", "permissions", "rbac"], reference: ["authorization", "authz", "iam", "identity"], boost: 18 },
  { name: "private-connectivity", query: ["private", "privatelink", "link", "connectivity", "connector", "cloudconnector", "scc", "onprem", "premise", "principal", "principalpropagation", "propagation", "odata"], reference: ["privatelink", "private", "connector", "cloudconnector", "connectivity", "odata", "e2b"], boost: 17 },
  { name: "agentic-ai-mcp", query: ["agent", "agents", "agentic", "mcp", "a2a", "tool", "tools", "joule", "copilot", "cline", "llm"], reference: ["agent", "agentic", "mcp", "a2a", "joule", "genai", "generative"], boost: 17 },
  { name: "generative-ai-rag", query: ["genai", "generative", "rag", "retrieval", "semantic", "embedding", "embeddings", "vector", "prompt"], reference: ["genai", "generative", "rag", "semantic", "agent2agent"], boost: 16 },
  { name: "business-data-cloud", query: ["bdc", "business", "data", "databricks", "snowflake", "hana", "datasphere", "analytics", "bw"], requiresAny: ["bdc", "data", "databricks", "snowflake", "hana", "datasphere", "analytics", "bw"], reference: ["bdc", "businessdatacloud", "databricks", "hyperscalerdata", "dataintegration"], boost: 15 },
  { name: "event-driven-integration", query: ["event", "events", "eventmesh", "eventing", "eda", "queue", "queues", "kafka", "message", "messages"], reference: ["eventdriven", "eda", "event", "integration", "e2b", "a2aintegration", "b2bintegration"], boost: 15 },
  { name: "resiliency", query: ["resiliency", "resilience", "multi", "region", "availability", "az", "failover", "load", "balancer", "disaster"], reference: ["resiliency", "multiregion", "multiaz", "loadbalancer"], boost: 14 },
  { name: "multitenant-saas-cap", query: ["cap", "saas", "tenant", "tenants", "multitenant", "multitenancy", "subscription"], reference: ["susaas", "cap", "multitenant"], boost: 14 },
  { name: "task-workflow-workzone", query: ["task", "tasks", "inbox", "workflow", "workzone", "work", "zone", "launchpad", "process", "automation", "spa"], reference: ["taskcenter", "buildworkzone", "buildprocessautomation"], boost: 14 },
  { name: "devops", query: ["devops", "cicd", "ci", "cd", "pipeline", "pipelines", "transport", "deploy", "deployment"], reference: ["devops"], boost: 20 },
  { name: "security-operations", query: ["siem", "soar", "threat", "detection", "audit", "security", "etd"], reference: ["siem", "soar", "etd"], boost: 20 },
  { name: "federated-ml", query: ["federated", "ml", "machine", "learning", "training", "model", "models", "aicore", "ai"], requiresAny: ["ml", "machine", "learning", "training", "model", "models", "aicore", "ai"], reference: ["federated", "ml", "machine", "learning", "aicore", "ai"], boost: 22 },
  { name: "edge-integration-cell", query: ["edge", "eic", "cell", "pipo", "pi", "po", "runtime", "migration"], reference: ["edge", "eic", "cell", "pipo", "integration"], boost: 20 },
  { name: "successfactors", query: ["successfactors", "hxm", "bizx", "employee", "recruiting", "module", "modules", "talent"], reference: ["successfactors", "hxm", "bizx", "recruiting"], boost: 22 }
].map((scenario) => ({
  ...scenario,
  query: new Set(scenario.query),
  requiresAny: new Set(scenario.requiresAny || []),
  reference: new Set(scenario.reference)
}));

const EXCLUSION_CLAUSE_SOURCE = String.raw`\b(?:exclude(?:s|d|ing)?|without|omit(?:s|ted|ting)?|do\s+not\s+include|don't\s+include|must\s+not\s+include|no)\b[^.;\n]*`;
const EXCLUSION_DIRECTIVES = new Set([
  "do", "don", "exclude", "excluded", "excludes", "excluding", "include",
  "must", "no", "not", "omit", "omits", "omitted", "omitting", "without"
]);

const metadataCache = new Map();

export function tokens(text = "") {
  const out = new Set();
  for (const rawToken of splitWords(text)) {
    const token = TOKEN_CANONICAL[rawToken] || rawToken;
    if (token.length >= 2 && !STOPWORDS.has(token)) out.add(token);
  }
  const joined = splitWords(text).join("");
  for (const compact of [
    "xsuaa",
    "privatelink",
    "workzone",
    "taskcenter",
    "eventmesh",
    "multiaz",
    "multiregion",
    "businessdatacloud",
    "successfactors",
    "cloudconnector",
    "principalpropagation"
  ]) {
    if (joined.includes(compact)) out.add(compact);
  }
  if (out.has("businessdatacloud")) out.add("bdc");
  if (joined.includes("aicore") || (out.has("ai") && out.has("core"))) out.add("aicore");
  if (joined.includes("cloudconnector")) out.add("cloudconnector");
  if (joined.includes("principalpropagation")) out.add("principalpropagation");
  if (joined.includes("s4hana") || out.has("4hana") || (out.has("s4") && out.has("hana"))) out.add("s4hana");
  if (out.has("ci") && out.has("cd")) out.add("cicd");
  if (out.has("pi") && out.has("po")) out.add("pipo");
  if (out.has("edge") && out.has("integration") && out.has("cell")) out.add("eic");
  return out;
}

export function querySignals(query) {
  const clauses = [...query.matchAll(new RegExp(EXCLUSION_CLAUSE_SOURCE, "gi"))].map((match) => match[0]);
  const positiveQuery = query.replace(new RegExp(EXCLUSION_CLAUSE_SOURCE, "gi"), " ");
  const excluded = new Set();
  for (const clause of clauses) {
    for (const token of tokens(clause)) {
      if (!EXCLUSION_DIRECTIVES.has(token)) excluded.add(token);
    }
  }
  return { positiveQuery, excluded };
}

export function setIntersection(a, b) {
  return [...a].filter((value) => b.has(value));
}

export function loadMetadata(referenceDir = referenceExamplesDir) {
  const path = join(referenceDir, "template-metadata.json");
  if (metadataCache.has(path)) return metadataCache.get(path);
  let metadata = { templates: {} };
  if (existsSync(path)) {
    try {
      metadata = JSON.parse(readFileSync(path, "utf8"));
    } catch {
      metadata = { templates: {} };
    }
  }
  metadataCache.set(path, metadata);
  return metadata;
}

export function templateMetadata(path, referenceDir = referenceExamplesDir) {
  return loadMetadata(referenceDir).templates?.[path.split(/[\\/]/).at(-1)] || {};
}

export function metadataSearchText(path, metadata = templateMetadata(path)) {
  if (!metadata) return "";
  const parts = [];
  for (const key of ["title", "summary", "family", "level", "domain"]) {
    if (typeof metadata[key] === "string") parts.push(metadata[key]);
  }
  for (const key of ["aliases", "tags", "products", "fallback_templates"]) {
    if (Array.isArray(metadata[key])) parts.push(...metadata[key].map(String));
  }
  return parts.join(" ");
}

export function drawioText(path) {
  const raw = readFileSync(path, "utf8");
  const parts = [path.split(/[\\/]/).at(-1).replace(/\.drawio$/i, "")];
  try {
    const doc = parseXml(raw);
    for (const elem of elementsByTag(doc, "*")) {
      for (const attr of ["name", "label", "value"]) {
        if (elem.hasAttribute(attr)) parts.push(elem.getAttribute(attr));
      }
    }
  } catch {
    parts.push(raw.slice(0, 10000));
  }
  let visible = decodeHTML(parts.join(" "));
  visible = visible.replace(/<br\s*\/?>/gi, " ");
  visible = visible.replace(/<[^>]+>/g, " ");
  return visible;
}

export function phraseHits(query, phrases = []) {
  const queryClean = splitWords(query).join(" ");
  const hits = [];
  for (const phrase of phrases) {
    const phraseClean = splitWords(String(phrase)).join(" ");
    if (phraseClean.length >= 4 && queryClean.includes(phraseClean)) hits.push(String(phrase));
  }
  return hits;
}

function exactStemMentioned(path, query) {
  const name = path.split(/[\\/]/).at(-1);
  const stem = name.replace(/\.drawio$/i, "");
  const queryLower = query.toLowerCase();
  if (queryLower.includes(name.toLowerCase())) return true;
  const stemWords = splitWords(stem).join(" ");
  const queryWords = splitWords(query).join(" ");
  return stemWords.length >= 8 && queryWords.includes(stemWords);
}

function primaryVisualFallbackMentioned(path, query) {
  const match = query.match(/Primary SAP visual fallback template:\s*([A-Za-z0-9_.-]+)/i);
  if (!match) return false;
  return match[1].trim().replace(/\.$/, "").toLowerCase() === path.split(/[\\/]/).at(-1).toLowerCase();
}

function explicitLevel(query) {
  const match = query.match(/\bL([012])\b/i);
  return match ? `l${match[1]}` : null;
}

function explicitFamily(query) {
  const match = query.match(/\bRA(\d{4})\b/i);
  return match ? `ra${match[1]}` : null;
}

function hasAny(set, values) {
  for (const value of values) if (set.has(value)) return true;
  return false;
}

export function scoreReference(path, query) {
  const { positiveQuery, excluded: excludedTokens } = querySignals(query);
  const qTokens = tokens(positiveQuery);
  const metadata = templateMetadata(path);
  const docText = drawioText(path);
  const metaText = metadataSearchText(path, metadata);
  const dTokens = tokens(docText);
  const mTokens = tokens(metaText);
  const filename = path.split(/[\\/]/).at(-1);
  const stem = filename.replace(/\.drawio$/i, "");
  const filenameTokens = tokens(stem);
  const combinedTokens = new Set([...dTokens, ...mTokens]);
  const reasons = [];

  const tokenHits = setIntersection(qTokens, combinedTokens).sort();
  let value = tokenHits.length * 2.0;
  if (tokenHits.length) reasons.push(`token overlap: ${tokenHits.slice(0, 8).join(", ")}`);

  const filenameHits = setIntersection(qTokens, filenameTokens).sort();
  if (filenameHits.length) {
    value += filenameHits.length * 4.0;
    reasons.push(`filename match: ${filenameHits.slice(0, 8).join(", ")}`);
  }
  if (exactStemMentioned(path, query)) {
    value += 70;
    reasons.push("exact template filename mentioned (+70)");
  }
  if (primaryVisualFallbackMentioned(path, query)) {
    value += 90;
    reasons.push("primary visual fallback match (+90)");
  }

  const metaHits = setIntersection(qTokens, mTokens).sort();
  if (metaHits.length) {
    const boost = Math.min(36.0, metaHits.length * 4.0);
    value += boost;
    reasons.push(`metadata match: ${metaHits.slice(0, 8).join(", ")} (+${Math.trunc(boost)})`);
  }

  const aliasHits = phraseHits(positiveQuery, Array.isArray(metadata.aliases) ? metadata.aliases : []);
  if (aliasHits.length) {
    const boost = Math.min(30.0, 12.0 + (aliasHits.length - 1) * 6.0);
    value += boost;
    reasons.push(`alias phrase match: ${aliasHits.slice(0, 3).join(", ")} (+${Math.trunc(boost)})`);
  }

  const title = metadata.title;
  if (typeof title === "string" && phraseHits(positiveQuery, [title]).length) {
    value += 22;
    reasons.push("metadata title phrase match (+22)");
  }

  const level = explicitLevel(query);
  const family = explicitFamily(query);
  const filenameLower = filename.toLowerCase();
  const pathLower = path.toLowerCase();
  const metadataFamily = String(metadata.family || "").toLowerCase();
  const metadataLevel = String(metadata.level || "").toLowerCase();
  if (family) {
    if (pathLower.includes(family) || family === metadataFamily) {
      value += 24;
      reasons.push(`explicit ${family.toUpperCase()} family match (+24)`);
    } else if (/\bra\d{4}\b/.test(pathLower)) {
      value -= 8;
      reasons.push("different reference family penalty (-8)");
    } else {
      value -= 5;
      reasons.push("different reference source penalty (-5)");
    }
  }
  if (level) {
    if (filenameLower.includes(level) || level === metadataLevel) {
      value += 10;
      reasons.push(`explicit ${level.toUpperCase()} match`);
    } else if (/_l[012]\b/.test(filenameLower)) {
      value -= 3;
    }
  } else if (filenameLower.includes("_l2")) {
    value += 3;
    reasons.push("default L2 preference");
  }

  for (const scenario of SCENARIOS) {
    const qHit = setIntersection(qTokens, scenario.query);
    if (scenario.requiresAny.size && !setIntersection(qTokens, scenario.requiresAny).length) continue;
    let rHit = setIntersection(filenameTokens, scenario.reference);
    if (!rHit.length) rHit = setIntersection(mTokens, scenario.reference);
    if (qHit.length && rHit.length) {
      value += scenario.boost;
      reasons.push(`${scenario.name} boost (+${Math.trunc(scenario.boost)})`);
    }
  }

  const strongQueryTags = setIntersection(qTokens, new Set(["devops", "ml", "eic", "pipo", "siem", "soar", "successfactors", "embodied", "agentic"]));
  if (strongQueryTags.length && !strongQueryTags.some((tag) => filenameTokens.has(tag) || mTokens.has(tag))) {
    value -= 10;
    reasons.push("strong scenario mismatch penalty (-10)");
  }

  if (hasAny(qTokens, ["mcp", "a2a"]) && hasAny(filenameTokens, ["mcp", "a2a"])) {
    const broaderAgenticSignal = qTokens.has("agentic") && (qTokens.has("joule") || setIntersection(qTokens, new Set(["agent", "agents", "ai"])).length >= 2);
    if (!broaderAgenticSignal) {
      value += 20;
      reasons.push("exact MCP/A2A filename match (+20)");
    } else {
      value += 6;
      reasons.push("MCP/A2A filename match dampened (broader agentic-AI scenario) (+6)");
    }
  }

  const primaryFamilySignals = new Set([
    "agent", "agents", "agentic", "mcp", "a2a", "tool", "tools", "joule",
    "copilot", "cline", "llm", "genai", "generative", "ai"
  ]);
  if (metadata.primary && setIntersection(qTokens, primaryFamilySignals).length) {
    const subSignals = new Set(["embodied", "robotics", "procode", "developer", "code", "vscode", "ide", "studio", "ecosystem"]);
    if (!setIntersection(qTokens, subSignals).length) {
      value += 14;
      reasons.push("metadata primary-template boost (+14)");
    }
  }

  const excludedMetaHits = setIntersection(excludedTokens, new Set([...filenameTokens, ...mTokens])).sort();
  const excludedVisibleHits = setIntersection(
    excludedTokens,
    new Set([...dTokens].filter((token) => !filenameTokens.has(token) && !mTokens.has(token)))
  ).sort();
  if (excludedMetaHits.length) {
    const penalty = Math.min(32.0, excludedMetaHits.length * 8.0);
    value -= penalty;
    reasons.push(`excluded metadata/filename terms: ${excludedMetaHits.slice(0, 8).join(", ")} (-${Math.trunc(penalty)})`);
  }
  if (excludedVisibleHits.length) {
    const penalty = Math.min(12.0, excludedVisibleHits.length * 2.0);
    value -= penalty;
    reasons.push(`excluded visible terms: ${excludedVisibleHits.slice(0, 8).join(", ")} (-${Math.trunc(penalty)})`);
  }
  if (hasAny(qTokens, ["xsuaa", "oauth", "oidc", "saml"]) && (hasAny(filenameTokens, ["authentication", "authn"]) || (filenameLower.includes("cloud") && filenameLower.includes("identity")))) {
    value += 8;
    reasons.push("exact authentication filename match (+8)");
  }
  if (hasAny(qTokens, ["bdc", "businessdatacloud", "aicore"]) && hasAny(filenameTokens, ["bdc", "businessdatacloud", "aicore"])) {
    value += 12;
    reasons.push("exact BDC / AI Core filename match (+12)");
  }
  if (qTokens.has("aicore") && filenameTokens.has("aicore")) {
    value += 10;
    reasons.push("exact AI Core filename match (+10)");
  }
  if (qTokens.has("agentic") && qTokens.has("ai")) {
    const rootAgentic = filename === "ac_RA0029_AgenticAI_root.drawio";
    const embodiedTerms = new Set(["embodied", "robotic", "robotics", "physical"]);
    const rootSignals = setIntersection(qTokens, new Set(["gateway", "orchestrator", "capabilities", "subaccount", "businessdatacloud", "successfactors", "concur", "s4hana", "mcp"]));
    if (rootAgentic && !setIntersection(qTokens, embodiedTerms).length) {
      value += 24;
      reasons.push("generic Agentic AI root boost (+24)");
      if (rootSignals.length >= 2) {
        value += 12;
        reasons.push("Agentic AI root component match (+12)");
      }
    }
    if ((filenameTokens.has("embodied") || mTokens.has("embodied")) && !setIntersection(qTokens, embodiedTerms).length) {
      value -= 18;
      reasons.push("embodied-specific template penalty (-18)");
    }
  }
  if (filenameTokens.has("joule") && !qTokens.has("joule")) {
    value -= 12;
    reasons.push("Joule-specific template penalty (-12)");
  }
  if (metadata.generic && strongQueryTags.length) {
    value -= 12;
    reasons.push("generic template penalty for specific scenario (-12)");
  }
  if (filename.startsWith("btp_")) value += 1.0;
  if (!reasons.length) reasons.push("weak lexical match; review manually");

  return {
    path,
    score: pyRound(value, 1),
    reasons,
    token_hits: tokenHits.slice(0, 12),
    metadata_title: title ? String(title) : null,
    metadata_tags: Array.isArray(metadata.tags) ? metadata.tags.slice(0, 12) : []
  };
}

function collectDrawioFiles(dir) {
  const out = [];
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    const path = join(dir, entry.name);
    if (entry.isDirectory()) out.push(...collectDrawioFiles(path));
    else if (entry.name.toLowerCase().endsWith(".drawio")) out.push(path);
  }
  return out.sort();
}

export function referencePool() {
  return collectDrawioFiles(referenceExamplesDir);
}

export function rankReferences(query, { top = 5 } = {}) {
  return referencePool()
    .map((path) => scoreReference(path, query))
    .sort((a, b) => b.score - a.score || a.path.localeCompare(b.path))
    .slice(0, top);
}
