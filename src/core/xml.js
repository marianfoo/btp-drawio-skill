import { DOMParser, XMLSerializer } from "@xmldom/xmldom";

function escapeCanonicalAttr(value) {
  return String(value)
    .replace(/&/g, "&amp;")
    .replace(/"/g, "&quot;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/\t/g, "&#9;")
    .replace(/\n/g, "&#10;")
    .replace(/\r/g, "&#13;");
}

function escapeCanonicalText(value) {
  return String(value)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}

export function parseXml(text) {
  return new DOMParser().parseFromString(String(text), "application/xml");
}

export function serializeXml(node) {
  return new XMLSerializer().serializeToString(node);
}

export function elementsByTag(root, tagName = "*") {
  const out = [];
  const visit = (node) => {
    if (node.nodeType === 1 && (tagName === "*" || node.tagName === tagName)) {
      out.push(node);
    }
    for (let child = node.firstChild; child; child = child.nextSibling) {
      visit(child);
    }
  };
  visit(root);
  return out;
}

export function firstElementByTag(root, tagName) {
  return elementsByTag(root, tagName)[0] || null;
}

function canonicalNode(node) {
  if (node.nodeType === 1) {
    const attrs = [];
    for (let i = 0; i < node.attributes.length; i += 1) {
      const attr = node.attributes.item(i);
      attrs.push([attr.name, attr.value]);
    }
    attrs.sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0));
    const attrText = attrs.map(([name, value]) => ` ${name}="${escapeCanonicalAttr(value)}"`).join("");
    const children = [];
    for (let child = node.firstChild; child; child = child.nextSibling) {
      const value = canonicalNode(child);
      if (value) children.push(value);
    }
    return children.length ? `<${node.tagName}${attrText}>${children.join("")}</${node.tagName}>` : `<${node.tagName}${attrText}/>`;
  }
  if (node.nodeType === 3 || node.nodeType === 4) {
    const value = node.nodeValue || "";
    return /^\s*$/.test(value) ? "" : escapeCanonicalText(value);
  }
  return "";
}

export function canonicalizeXml(text) {
  const doc = parseXml(`<__canonical_root>${String(text).trim()}</__canonical_root>`);
  const root = doc.documentElement;
  const out = [];
  for (let child = root.firstChild; child; child = child.nextSibling) {
    const value = canonicalNode(child);
    if (value) out.push(value);
  }
  return out.join("");
}
