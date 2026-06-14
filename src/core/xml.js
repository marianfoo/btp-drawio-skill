import { DOMParser, XMLSerializer } from "@xmldom/xmldom";

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
