export function parseStyle(style = "", { includeBare = true } = {}) {
  const out = {};
  if (!style) return out;
  for (const rawPart of String(style).split(";")) {
    const part = rawPart.trim();
    if (!part) continue;
    const idx = part.indexOf("=");
    if (idx >= 0) {
      out[part.slice(0, idx).trim()] = part.slice(idx + 1).trim();
    } else if (includeBare) {
      out[part] = "1";
    }
  }
  return out;
}

export function parseValidateStyle(style = "") {
  return parseStyle(style, { includeBare: true });
}

export function parseCompareStyle(style = "") {
  return parseStyle(style, { includeBare: false });
}
