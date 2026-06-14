import { readFileSync, writeFileSync } from "node:fs";
import { parseXml, serializeXml, elementsByTag } from "../core/xml.js";
import { cleanLabel, LABEL_ATTRS, replaceInnerSimpleHtml } from "../core/labels.js";
import { fail, ok } from "./result.js";

export function parseMappingText(text) {
  const data = JSON.parse(text);
  if (!data || typeof data !== "object" || Array.isArray(data)) {
    throw new Error("mapping JSON must be an object");
  }

  const rawIds = Object.hasOwn(data, "ids") || Object.hasOwn(data, "labels") ? data.ids || {} : {};
  const rawLabels = Object.hasOwn(data, "ids") || Object.hasOwn(data, "labels") ? data.labels || {} : data;
  if (!rawIds || typeof rawIds !== "object" || Array.isArray(rawIds) || !rawLabels || typeof rawLabels !== "object" || Array.isArray(rawLabels)) {
    throw new Error("'ids' and 'labels' must be objects when present");
  }

  const ids = new Map(Object.entries(rawIds).map(([key, value]) => [String(key), String(value)]));
  const labels = new Map(Object.entries(rawLabels).map(([key, value]) => [cleanLabel(String(key)), String(value)]));
  return { ids, labels };
}

export function relabelXml(xml, mappingText) {
  const mapping = parseMappingText(mappingText);
  const doc = parseXml(xml);
  const replacements = [];

  for (const elem of elementsByTag(doc, "*")) {
    const elementId = elem.getAttribute("id") || "";
    const attr = LABEL_ATTRS.find((name) => elem.hasAttribute(name));
    if (!attr) continue;

    const raw = elem.getAttribute(attr) || "";
    let newValue = null;
    let matchedBy = "";
    if (mapping.ids.has(elementId)) {
      newValue = mapping.ids.get(elementId);
      matchedBy = `id:${elementId}`;
    } else {
      const visible = cleanLabel(raw);
      if (mapping.labels.has(visible)) {
        newValue = mapping.labels.get(visible);
        matchedBy = `label:${visible}`;
      }
    }
    if (newValue === null) continue;

    const updated = replaceInnerSimpleHtml(raw, newValue);
    if (updated === raw) continue;
    elem.setAttribute(attr, updated);
    replacements.push({
      element_id: elementId,
      attr,
      old: cleanLabel(raw),
      new: cleanLabel(updated),
      matched_by: matchedBy
    });
  }

  return { xml: serializeXml(doc), replacements };
}

function summary(replacements) {
  const lines = [`relabel: replaced ${replacements.length} label(s)`];
  for (const item of replacements) {
    lines.push(`  ${item.matched_by}: '${item.old}' -> '${item.new}'`);
  }
  return `${lines.join("\n")}\n`;
}

export function relabel(options) {
  if (!options.file) return fail(2, "usage: relabel <drawio> <mapping> --out <file>|--write\n");
  if (options.out && options.write) return fail(2, "use either --out or --write, not both\n");
  if (!options.out && !options.write) return fail(2, "pass --write or --out\n");
  if (!options.mapping && !options.mappingJson) return fail(2, "mapping path or mappingJson required\n");

  try {
    const mappingText = options.mappingJson ?? readFileSync(options.mapping, "utf8");
    const { xml, replacements } = relabelXml(readFileSync(options.file, "utf8"), mappingText);
    writeFileSync(options.write ? options.file : options.out, xml, "utf8");
    return ok("", summary(replacements));
  } catch (error) {
    return fail(1, `relabel failed: ${error.message}\n`);
  }
}
