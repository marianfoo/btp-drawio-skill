import { copyFileSync, existsSync, readFileSync, writeFileSync } from "node:fs";
import { pyRound } from "../core/round.js";
import { fail, ok } from "./result.js";

const GRID = 10;
const ALLOWED_STROKE_VALUES = [1.0, 1.5, 2.0, 3.0, 4.0];
const STAT_KEYS = ["geometry", "hex_case", "arc_size", "stroke_width", "font_family", "xml_comments"];

function emptyStats() {
  return Object.fromEntries(STAT_KEYS.map((key) => [key, 0]));
}

function snap(value) {
  return pyRound(Number(value) / GRID) * GRID;
}

export function fixGeometry(text, stats) {
  if (/<mxGraphModel\b[^>]*\bgrid="0"/.test(text)) return text;
  return text.replace(/\b(x|y|width|height)="(-?\d+(?:\.\d+)?)"/g, (_match, attr, rawNumber) => {
    const num = Number(rawNumber);
    const snapped = snap(num);
    if (Math.abs(num - snapped) > 0.001) stats.geometry += 1;
    return `${attr}="${snapped}"`;
  });
}

function fixHexChunk(chunk, stats) {
  return chunk.replace(/#[0-9a-fA-F]{6}\b/g, (hex) => {
    const upper = hex.toUpperCase();
    if (hex !== upper) stats.hex_case += 1;
    return upper;
  });
}

export function fixHexCase(text, stats) {
  const chunks = [];
  let i = 0;
  while (i < text.length) {
    const match = /data:image\/[^&";]+/.exec(text.slice(i));
    if (!match) {
      chunks.push(fixHexChunk(text.slice(i), stats));
      break;
    }
    const start = i + match.index;
    const end = start + match[0].length;
    chunks.push(fixHexChunk(text.slice(i, start), stats));
    chunks.push(text.slice(start, end));
    i = end;
  }
  return chunks.join("");
}

export function fixArcSize(text, stats) {
  return text.replace(/style="([^"]*)"/g, (match, styleValue) => {
    if (styleValue.includes("arcSize=") && !styleValue.includes("absoluteArcSize=")) {
      stats.arc_size += 1;
      const trailing = styleValue.endsWith(";") ? "" : ";";
      return `style="${styleValue}${trailing}absoluteArcSize=1;"`;
    }
    return match;
  });
}

export function fixStrokeWidth(text, stats) {
  return text.replace(/strokeWidth=([0-9.]+)/g, (match, rawValue) => {
    const value = Number(rawValue);
    const nearest = ALLOWED_STROKE_VALUES.reduce((best, candidate) =>
      Math.abs(candidate - value) < Math.abs(best - value) ? candidate : best
    );
    if (Math.abs(nearest - value) < 0.01) return match;
    stats.stroke_width += 1;
    return `strokeWidth=${Number.isInteger(nearest) ? String(nearest) : String(nearest)}`;
  });
}

export function fixFontFamily(text, stats) {
  return text.replace(/fontFamily=([^;"]+)/g, (match, value) => {
    if (value.toLowerCase() === "helvetica") return match;
    stats.font_family += 1;
    return "fontFamily=Helvetica";
  });
}

export function fixStripComments(text, stats) {
  const matches = text.match(/<!--[\s\S]*?-->/g);
  if (matches?.length) {
    stats.xml_comments += matches.length;
    return text.replace(/<!--[\s\S]*?-->/g, "");
  }
  return text;
}

export function applyAutofix(text) {
  const stats = emptyStats();
  let fixed = text;
  fixed = fixStripComments(fixed, stats);
  fixed = fixGeometry(fixed, stats);
  fixed = fixHexCase(fixed, stats);
  fixed = fixArcSize(fixed, stats);
  fixed = fixStrokeWidth(fixed, stats);
  fixed = fixFontFamily(fixed, stats);
  return { fixed, stats };
}

function totalStats(stats) {
  return STAT_KEYS.reduce((total, key) => total + stats[key], 0);
}

function summarizeStats(stats) {
  return STAT_KEYS.filter((key) => stats[key]).map((key) => `${key}=${stats[key]}`).join(", ");
}

export function autofix(options) {
  const file = options.file;
  if (!file) return fail(2, "usage: autofix <file.drawio> [--write]\n");
  if (!existsSync(file)) return fail(1, `${file}: not found\n`);

  const original = readFileSync(file, "utf8");
  const { fixed, stats } = applyAutofix(original);
  const total = totalStats(stats);
  if (total === 0) return ok(`${file}: no fixes needed\n`);

  const summary = summarizeStats(stats);
  if (options.write) {
    copyFileSync(file, `${file}.bak`);
    writeFileSync(file, fixed, "utf8");
    return ok(`${file}: wrote (${total} fixes - ${summary}); backup at ${file.split(/[\\/]/).at(-1)}.bak\n`);
  }
  return ok(`${file}: would fix (${total} changes - ${summary}); re-run with --write\n`);
}
