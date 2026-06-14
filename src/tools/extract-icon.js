import { readFileSync } from "node:fs";
import { iconIndexPath } from "../core/paths.js";
import { snap10 } from "../core/round.js";
import { xmlEscapeAttr } from "../core/labels.js";
import { extractAsset, findAsset, loadAssetIndex, normalize as normalizeAsset } from "./extract-asset.js";
import { fail, ok } from "./result.js";

export const COMMON_ALIASES = {
  xsuaa: "sap-authorization-10-and-10-trust-management-service",
  uaa: "sap-authorization-10-and-10-trust-management-service",
  "auth trust": "sap-authorization-10-and-10-trust-management-service",
  ias: "identity-10-authentication",
  ips: "identity-provisioning",
  "btp cockpit": "sap-btp-cockpit",
  hana: "sap-hana-cloud",
  "hana cloud": "sap-hana-cloud",
  cf: "cloud-10-foundry-runtime",
  "cloud foundry": "cloud-10-foundry-runtime",
  cap: "cloud-application-programming",
  destination: "sap-destination-10-service",
  cc: "cloud-10-connector",
  connector: "cloud-10-connector",
  "abap env": "abap-environment",
  "abap environment": "abap-environment",
  "build apps": "sap-build-apps",
  "build process": "sap-build-process-automation",
  "build code": "sap-build-code",
  "build work zone": "sap-build-work-zone-10-standard-edition",
  "sap build work zone": "sap-build-work-zone-10-standard-edition",
  "work zone": "sap-build-work-zone-10-standard-edition",
  joule: "joule-studio",
  "task center": "sap-task-center",
  cpi: "cloud-10-integration",
  "integration suite": "integration-suite"
};

export function loadIconIndex() {
  return JSON.parse(readFileSync(iconIndexPath, "utf8"));
}

function normalize(text = "") {
  let value = String(text).toLowerCase();
  value = value.replace(/&#?\w+;/g, " ");
  value = value.replace(/(^|-)10(-|$)/g, "$1 $2");
  return value.replace(/[^a-z0-9]+/g, " ").trim();
}

function tokens(text = "") {
  return new Set(normalize(text).split(/\s+/).filter(Boolean));
}

function isSubset(needle, haystack) {
  for (const value of needle) {
    if (!haystack.has(value)) return false;
  }
  return true;
}

export function isBackendSystemQuery(query) {
  const normalized = normalize(query);
  const compact = String(query).toLowerCase().replace(/[^a-z0-9]+/g, "");
  return (
    ["sap s 4hana", "sap s 4hana cloud", "s 4hana", "s 4hana cloud"].includes(normalized) ||
    ["s4hana", "saps4hana", "s4hanacloud", "saps4hanacloud"].includes(compact)
  );
}

export function backendSystemGuidance(query) {
  return `'${query}' is a backend system/product label, not a BTP service icon. Use extract_asset.py "sap-s-4hana" --kind sap-brand-name for the label or extract_asset.py "on-premise-sap" --kind generic-icon for a generic backend icon.`;
}

export function findIcon(index, query) {
  if (isBackendSystemQuery(query)) return null;
  const q = String(query).toLowerCase().trim();
  const qslug = q.replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "");
  if (COMMON_ALIASES[q] && index[COMMON_ALIASES[q]]) return [COMMON_ALIASES[q], index[COMMON_ALIASES[q]]];
  if (index[qslug]) return [qslug, index[qslug]];

  for (const [slug, entry] of Object.entries(index)) {
    if ((entry.aliases || []).includes(qslug) || qslug === String(entry.display).toLowerCase()) {
      return [slug, entry];
    }
  }

  const qtokens = tokens(q);
  if (!qtokens.size) return null;
  const tokenCandidates = [];
  for (const [slug, entry] of Object.entries(index)) {
    const pool = new Set([...tokens(slug), ...tokens(entry.display)]);
    for (const alias of entry.aliases || []) {
      for (const token of tokens(alias)) pool.add(token);
    }
    if (isSubset(qtokens, pool)) tokenCandidates.push([slug, entry]);
  }
  if (tokenCandidates.length === 1) return tokenCandidates[0];
  if (tokenCandidates.length > 1) {
    tokenCandidates.sort((a, b) => normalize(a[1].display).length - normalize(b[1].display).length);
    const top = normalize(tokenCandidates[0][1].display);
    const second = normalize(tokenCandidates[1][1].display);
    if (top.length < second.length) return tokenCandidates[0];
    const error = new Error(`ambiguous '${query}' - ${tokenCandidates.length} matches`);
    error.matches = tokenCandidates.slice(0, 10);
    throw error;
  }

  const candidates = Object.entries(index).filter(([slug, entry]) => q && (String(entry.display).toLowerCase().includes(q) || slug.includes(qslug)));
  if (candidates.length === 1) return candidates[0];
  if (candidates.length > 1) {
    const error = new Error(`ambiguous '${query}' - ${candidates.length} matches`);
    error.matches = candidates.slice(0, 10);
    throw error;
  }
  return null;
}

function formatAmbiguous(error) {
  if (!error.matches) return `${error.message}\n`;
  const lines = [`${error.message}:`];
  for (const [slug, entry] of error.matches) {
    lines.push(`  ${slug}  -  ${entry.display}`);
  }
  return `${lines.join("\n")}\n`;
}

export function extractIcon(options) {
  const opts = {
    x: Number(options.x ?? 0),
    y: Number(options.y ?? 0),
    w: Number(options.w ?? 32),
    h: Number(options.h ?? 32),
    id: options.id || "icon1",
    parent: options.parent || "1",
    label: options.label,
    query: options.query,
    list: Boolean(options.list)
  };

  const index = loadIconIndex();
  if (opts.list) {
    let assetIndex = null;
    try {
      assetIndex = loadAssetIndex();
    } catch {
      assetIndex = null;
    }
    if (assetIndex) {
      const lines = [];
      for (const key of Object.keys(assetIndex.assets).sort()) {
        const entry = assetIndex.assets[key];
        if (entry.kind === "btp-service-icon") {
          lines.push(`${key.split(":", 2)[1].padEnd(60)}  ${entry.display}`);
        }
      }
      return ok(`${lines.join("\n")}${lines.length ? "\n" : ""}`);
    }
    const lines = Object.keys(index).sort().map((slug) => `${slug.padEnd(60)}  ${index[slug].display}`);
    return ok(`${lines.join("\n")}${lines.length ? "\n" : ""}`);
  }
  if (!opts.query) return fail(2, "usage: extract-icon <query>\n");
  if (isBackendSystemQuery(opts.query)) return fail(1, `${backendSystemGuidance(opts.query)}\n`);

  const preferIconIndex = Object.hasOwn(COMMON_ALIASES, String(opts.query).toLowerCase().trim());
  if (!preferIconIndex) {
    try {
      const assetIndex = loadAssetIndex();
      const assetMatch = findAsset(assetIndex, opts.query, "btp-service-icon");
      if (assetMatch) {
        return extractAsset({ ...opts, kind: "btp-service-icon", id: opts.id || "icon1" });
      }
    } catch {
      // Fall back to the legacy icon index below.
    }
  }

  let match;
  try {
    match = findIcon(index, opts.query);
  } catch (error) {
    return fail(2, formatAmbiguous(error));
  }
  if (!match) return fail(1, `no icon matches '${opts.query}'\n`);
  const [slug, entry] = match;
  const label = opts.label ?? entry.label;
  const cell = `<mxCell id="${xmlEscapeAttr(opts.id)}" value="${xmlEscapeAttr(label)}" style="${xmlEscapeAttr(entry.style)}" vertex="1" parent="${xmlEscapeAttr(opts.parent)}"><mxGeometry x="${snap10(opts.x)}" y="${snap10(opts.y)}" width="${snap10(opts.w)}" height="${snap10(opts.h)}" as="geometry"/></mxCell>`;
  return ok(`${cell}\n`, `# matched: ${slug} - ${entry.display}\n`);
}
