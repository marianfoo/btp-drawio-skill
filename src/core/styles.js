export function parseStyle(style = "") {
  const out = {};
  if (!style) return out;
  for (const rawPart of String(style).split(";")) {
    const part = rawPart.trim();
    if (!part) continue;
    const idx = part.indexOf("=");
    if (idx >= 0) {
      out[part.slice(0, idx).trim()] = part.slice(idx + 1).trim();
    } else {
      out[part] = "1";
    }
  }
  return out;
}
