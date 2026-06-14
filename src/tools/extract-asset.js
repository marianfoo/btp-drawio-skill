import { readFileSync } from "node:fs";
import { join } from "node:path";
import { decodeHTML } from "entities";
import { assetIndexPath, librariesDir } from "../core/paths.js";
import { snap10 } from "../core/round.js";
import { parseXml, serializeXml, elementsByTag } from "../core/xml.js";
import { xmlEscapeAttr } from "../core/labels.js";
import { fail, ok } from "./result.js";

export function loadAssetIndex() {
  return JSON.parse(readFileSync(assetIndexPath, "utf8"));
}

export function normalize(text = "") {
  return String(text).toLowerCase().replace(/[^a-z0-9]+/g, " ").trim();
}

export function slugify(text = "") {
  return String(text).toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "");
}

export function assetTokens(text = "") {
  return new Set(normalize(text).split(/\s+/).filter(Boolean));
}

function isSubset(needle, haystack) {
  for (const value of needle) {
    if (!haystack.has(value)) return false;
  }
  return true;
}

export function findAsset(index, query, kind = null) {
  const assets = index.assets;
  const queryRaw = String(query || "").trim();
  const querySlug = slugify(queryRaw);
  const queryTokens = assetTokens(queryRaw);
  const filtered = Object.entries(assets).filter(([, asset]) => !kind || asset.kind === kind);

  for (const [key, asset] of filtered) {
    const keyShort = key.split(":", 2).at(-1);
    if (
      queryRaw === key ||
      queryRaw === keyShort ||
      querySlug === slugify(key) ||
      querySlug === slugify(keyShort)
    ) {
      return [key, asset];
    }
    if ((asset.aliases || []).some((alias) => querySlug === slugify(alias))) {
      return [key, asset];
    }
  }

  const candidates = [];
  for (const [key, asset] of filtered) {
    const pool = new Set([
      ...assetTokens(key),
      ...assetTokens(asset.display),
      ...assetTokens(asset.title || "")
    ]);
    for (const alias of asset.aliases || []) {
      for (const token of assetTokens(alias)) pool.add(token);
    }
    if (queryTokens.size && isSubset(queryTokens, pool)) {
      candidates.push([pool.size, key, asset]);
    }
  }
  if (candidates.length === 1) return [candidates[0][1], candidates[0][2]];
  if (candidates.length > 1) {
    candidates.sort((a, b) => a[0] - b[0] || a[1].localeCompare(b[1]));
    const [top, second] = candidates;
    if (top[0] < second[0]) return [top[1], top[2]];
    const error = new Error(`ambiguous '${queryRaw}' - ${candidates.length} matches`);
    error.matches = candidates.slice(0, 12).map(([, key, asset]) => [key, asset]);
    throw error;
  }

  const substring = filtered.filter(([key, asset]) => normalize(asset.display).includes(normalize(queryRaw)) || key.includes(querySlug));
  if (substring.length === 1) return substring[0];
  if (substring.length > 1) {
    const error = new Error(`ambiguous '${queryRaw}' - ${substring.length} matches`);
    error.matches = substring.slice(0, 12);
    throw error;
  }
  return null;
}

function loadLibraryEntry(asset) {
  const path = join(librariesDir, asset.library);
  const raw = readFileSync(path, "utf8").replace(/<!--[\s\S]*?-->/g, "").trim();
  const body = raw.slice("<mxlibrary>".length, raw.length - "</mxlibrary>".length).trim();
  return JSON.parse(body)[asset.entry];
}

function mxcellForData(asset, libraryEntry, args) {
  const width = snap10(args.w ?? Number(asset.width || 40));
  const height = snap10(args.h ?? Number(asset.height || 40));
  const label = args.label ?? asset.display;
  const style = `shape=image;verticalLabelPosition=bottom;verticalAlign=top;aspect=fixed;imageAspect=0;image=${libraryEntry.data};`;
  return `<mxCell id="${xmlEscapeAttr(args.id)}" value="${xmlEscapeAttr(label)}" style="${xmlEscapeAttr(style)}" vertex="1" parent="${xmlEscapeAttr(args.parent)}"><mxGeometry x="${snap10(args.x)}" y="${snap10(args.y)}" width="${width}" height="${height}" as="geometry"/></mxCell>`;
}

function setEdgePoints(cell, x, y, width, height) {
  for (const point of elementsByTag(cell, "mxPoint")) {
    const as = point.getAttribute("as");
    if (as === "sourcePoint") {
      point.setAttribute("x", String(x));
      point.setAttribute("y", String(y));
    } else if (as === "targetPoint") {
      point.setAttribute("x", String(x + width));
      point.setAttribute("y", String(y + height));
    }
  }
}

function mxCellsForXml(asset, libraryEntry, args) {
  const doc = parseXml(decodeHTML(libraryEntry.xml));
  const cells = elementsByTag(doc, "mxCell")
    .filter((cell) => !["0", "1"].includes(cell.getAttribute("id")))
    .map((cell) => cell.cloneNode(true));
  if (!cells.length) throw new Error(`${asset.display} contains no extractable mxCell`);

  const idMap = new Map();
  cells.forEach((cell, index) => {
    const oldId = cell.getAttribute("id");
    if (oldId) idMap.set(oldId, index === 0 ? args.id : `${args.id}-${index + 1}`);
  });

  const originalTopIds = new Set(cells.filter((cell) => cell.getAttribute("parent") === "1").map((cell) => cell.getAttribute("id")));
  const x = snap10(args.x);
  const y = snap10(args.y);
  const width = args.w !== undefined ? snap10(args.w) : snap10(Number(asset.width || 120));
  const height = args.h !== undefined ? snap10(args.h) : 0;

  for (const cell of cells) {
    const oldId = cell.getAttribute("id");
    const oldParent = cell.getAttribute("parent");
    if (idMap.has(oldId)) cell.setAttribute("id", idMap.get(oldId));
    if (oldParent === "1") cell.setAttribute("parent", args.parent);
    else if (idMap.has(oldParent)) cell.setAttribute("parent", idMap.get(oldParent));
    for (const ref of ["source", "target"]) {
      const value = cell.getAttribute(ref);
      if (idMap.has(value)) cell.setAttribute(ref, idMap.get(value));
    }

    if (args.label !== undefined && originalTopIds.has(oldId)) {
      cell.setAttribute("value", args.label);
    }

    const geometry = elementsByTag(cell, "mxGeometry")[0];
    if (geometry && originalTopIds.has(oldId) && cell.getAttribute("vertex") === "1") {
      geometry.setAttribute("x", String(x));
      geometry.setAttribute("y", String(y));
      if (args.w !== undefined) geometry.setAttribute("width", String(width));
      if (args.h !== undefined) geometry.setAttribute("height", String(snap10(args.h)));
    }
    if (cell.getAttribute("edge") === "1" && originalTopIds.has(oldId)) {
      setEdgePoints(cell, x, y, width, height);
    }
  }

  return cells.map((cell) => serializeXml(cell)).join("\n");
}

export function emitAsset(asset, args) {
  const libraryEntry = loadLibraryEntry(asset);
  if (libraryEntry.data) return mxcellForData(asset, libraryEntry, args);
  if (libraryEntry.xml) return mxCellsForXml(asset, libraryEntry, args);
  throw new Error(`unsupported library entry for ${asset.display}`);
}

function formatAmbiguous(error) {
  if (!error.matches) return `${error.message}\n`;
  const lines = [`${error.message}:`];
  for (const [key, asset] of error.matches) {
    lines.push(`  ${key} - ${asset.display}`);
  }
  return `${lines.join("\n")}\n`;
}

export function extractAsset(options) {
  const index = loadAssetIndex();
  if (options.list) {
    const lines = [];
    for (const [key, asset] of Object.entries(index.assets)) {
      if (!options.kind || asset.kind === options.kind) {
        lines.push(`${key.padEnd(70)} ${asset.display}`);
      }
    }
    return ok(`${lines.join("\n")}${lines.length ? "\n" : ""}`);
  }
  if (!options.query) return fail(2, "usage: extract-asset <query> [--kind kind]\n");

  let match;
  try {
    match = findAsset(index, options.query, options.kind || null);
  } catch (error) {
    return fail(2, formatAmbiguous(error));
  }
  if (!match) return fail(1, `no asset matches '${options.query}'\n`);
  const [key, asset] = match;
  try {
    const stdout = `${emitAsset(asset, normalizeOptions(options))}\n`;
    return ok(stdout, `# matched: ${key} - ${asset.display}\n`);
  } catch (error) {
    return fail(1, `${error.message}\n`);
  }
}

export function normalizeOptions(options = {}) {
  return {
    query: options.query,
    list: Boolean(options.list),
    kind: options.kind,
    x: Number(options.x ?? 0),
    y: Number(options.y ?? 0),
    w: options.w === undefined ? undefined : Number(options.w),
    h: options.h === undefined ? undefined : Number(options.h),
    id: options.id || "asset1",
    parent: options.parent || "1",
    label: options.label
  };
}
