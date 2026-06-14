import { decodeHTML } from "entities";

export const LABEL_ATTRS = ["value", "label", "name"];

export function cleanLabel(value = "") {
  let text = decodeHTML(String(value));
  text = text.replace(/<br\s*\/?>/gi, " ");
  text = text.replace(/<[^>]+>/g, " ");
  text = text.replace(/&nbsp;/g, " ");
  return text.replace(/\s+/g, " ").trim();
}

export function asDrawioLabel(value = "") {
  return String(value).replace(/\r\n/g, "\n").replace(/\r/g, "\n").replace(/\n/g, "<br>");
}

export function replaceInnerSimpleHtml(raw = "", newValue = "") {
  const replacement = asDrawioLabel(newValue);
  const match = String(raw).match(/^(<(?<tag>b|i|u|font|span)\b[^>]*>)([\s\S]*)(<\/\k<tag>>)$/i);
  if (match) {
    return `${match[1]}${replacement}${match[4]}`;
  }
  return replacement;
}

export function splitWords(text = "") {
  let value = String(text);
  value = value.replace(/([A-Z]+)([A-Z][a-z])/g, "$1 $2");
  value = value.replace(/([a-z])([A-Z])/g, "$1 $2");
  value = value.replace(/[_\-/]/g, " ");
  return [...value.matchAll(/[A-Za-z0-9]+/g)].map((match) => match[0].toLowerCase());
}

export function xmlEscapeAttr(value = "") {
  return String(value)
    .replace(/&/g, "&amp;")
    .replace(/"/g, "&quot;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}
