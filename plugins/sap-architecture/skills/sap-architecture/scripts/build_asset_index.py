#!/usr/bin/env python3
"""Build a searchable index for all bundled SAP draw.io libraries.

The service-only icon index is kept for backwards compatibility with
extract_icon.py. This broader index covers the full SAP starter-kit surface
that is useful to an LLM: BTP service icons, generic icons, connectors, area
shapes, number bubbles, product names, text elements, and interface labels.
"""
from __future__ import annotations

import json
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any
from xml.sax.saxutils import unescape

HERE = Path(__file__).resolve().parent
ASSETS = HERE.parent / "assets"
LIB_DIR = ASSETS / "libraries"
OUT = ASSETS / "asset-index.json"

LIBRARY_KINDS = {
    "btp-service-icons-all-size-M.xml": "btp-service-icon",
    "sap-generic-icons-size-M-200302.xml": "generic-icon",
    "connectors.xml": "connector",
    "area_shapes.xml": "area-shape",
    "default_shapes.xml": "default-shape",
    "essentials.xml": "essential-shape",
    "numbers.xml": "number-marker",
    "sap_brand_names.xml": "sap-brand-name",
    "text_elements.xml": "text-element",
    "annotations_and_interfaces.xml": "annotation-interface",
}


def clean_text(value: str) -> str:
    value = unescape(value)
    value = value.replace("&amp;#10;", " ").replace("&#10;", " ").replace("\\n", " ")
    value = re.sub(r"<br\s*/?>", " ", value, flags=re.I)
    value = re.sub(r"<[^>]+>", " ", value)
    value = re.sub(r"&nbsp;|\xa0", " ", value)
    value = re.sub(r"\s+", " ", value).strip()
    return value


def humanize(value: str | None) -> str:
    if not value:
        return ""
    value = re.sub(r"^\d+-", "", value)
    value = re.sub(r"_sd$", "", value)
    value = re.sub(r"[-_]+", " ", value)
    value = re.sub(r"\bsize [sml]\b", "", value, flags=re.I)
    value = re.sub(r"\s+", " ", value).strip()
    return value


def slugify(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")


def load_mxlibrary(path: Path) -> list[dict[str, Any]]:
    raw = path.read_text(encoding="utf-8")
    raw = re.sub(r"<!--.*?-->", "", raw, flags=re.S).strip()
    if not raw.startswith("<mxlibrary>") or not raw.endswith("</mxlibrary>"):
        raise ValueError(f"{path} is not a draw.io mxlibrary")
    body = raw[len("<mxlibrary>") : -len("</mxlibrary>")].strip()
    return json.loads(body)


def first_cell_text(xml: str) -> str:
    try:
        root = ET.fromstring(xml)
    except ET.ParseError:
        return ""
    for cell in root.iter("mxCell"):
        value = clean_text(cell.get("value") or "")
        if value:
            return value
    return ""


def first_cell_style(xml: str) -> str:
    try:
        root = ET.fromstring(xml)
    except ET.ParseError:
        return ""
    for cell in root.iter("mxCell"):
        style = cell.get("style") or ""
        if cell.get("id") not in {"0", "1"} and style:
            return style
    return ""


def infer_untitled_display(kind: str, library: str, entry_index: int, xml: str) -> str:
    style = first_cell_style(xml).lower()
    hints: list[str] = []
    if "#0070f2" in style or "#ebf8ff" in style:
        hints.append("SAP BTP")
    if "#475e75" in style or "#f5f6f7" in style:
        hints.append("non-SAP")
    if "dashed=1" in style:
        hints.append("dashed")
    if "ellipse" in style:
        hints.append("ellipse")
    if "group" in style:
        hints.append("group")
    if "fillcolor=#ffffff" in style:
        hints.append("white fill")
    base = humanize(library.replace(".xml", ""))
    suffix = " ".join(hints) if hints else f"entry {entry_index + 1:02d}"
    return f"{base} {suffix}".strip()


def aliases_for(display: str, title: str, kind: str, library: str) -> list[str]:
    aliases = {slugify(display), slugify(title), slugify(humanize(title)), slugify(kind), slugify(library)}
    words = slugify(display)
    replacements = {
        "sap-business-technology-platform": "sap-btp",
        "business-technology-platform": "btp",
        "authorization-and-trust-management": "xsuaa",
        "cloud-integration": "cpi",
        "cloud-connector": "cc",
        "cloud-foundry-runtime": "cf",
        "identity-authentication": "ias",
        "identity-provisioning": "ips",
        "sap-destination-service": "destination",
        "sap-hana-cloud": "hana",
    }
    for old, new in replacements.items():
        if old in words:
            aliases.add(words.replace(old, new))
    return sorted(a for a in aliases if a and a != slugify(display))


def entry_display(kind: str, library: str, entry_index: int, entry: dict[str, Any]) -> str:
    title = humanize(entry.get("title"))
    if "xml" in entry:
        xml = unescape(entry["xml"])
        return first_cell_text(xml) or title or infer_untitled_display(kind, library, entry_index, xml)
    return title or f"{humanize(library)} entry {entry_index + 1:02d}"


def build() -> dict[str, Any]:
    assets: dict[str, dict[str, Any]] = {}
    libraries: dict[str, dict[str, Any]] = {}

    for library, kind in sorted(LIBRARY_KINDS.items()):
        path = LIB_DIR / library
        if not path.exists():
            continue
        entries = load_mxlibrary(path)
        libraries[library] = {"kind": kind, "entries": len(entries)}
        used_slugs: dict[str, int] = {}

        for entry_index, entry in enumerate(entries):
            display = entry_display(kind, library, entry_index, entry)
            slug = slugify(display) or f"{kind}-{entry_index + 1:03d}"
            if slug in used_slugs:
                used_slugs[slug] += 1
                slug = f"{slug}-{used_slugs[slug]}"
            else:
                used_slugs[slug] = 1

            key = f"{kind}:{slug}"
            title = entry.get("title") or ""
            assets[key] = {
                "kind": kind,
                "display": display,
                "title": title,
                "aliases": aliases_for(display, title, kind, library),
                "library": library,
                "entry": entry_index,
                "width": entry.get("w"),
                "height": entry.get("h"),
                "aspect": entry.get("aspect"),
                "source": "data" if "data" in entry else "xml",
            }

    return {
        "metadata": {
            "source": "SAP/btp-solution-diagrams assets/shape-libraries-and-editable-presets/draw.io",
            "count": len(assets),
            "libraries": libraries,
        },
        "assets": dict(sorted(assets.items())),
    }


def main() -> int:
    missing = sorted(name for name in LIBRARY_KINDS if not (LIB_DIR / name).exists())
    if missing:
        print("missing libraries:", ", ".join(missing), file=sys.stderr)
        return 1
    index = build()
    OUT.write_text(json.dumps(index, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
    print(f"wrote {OUT} — {index['metadata']['count']} assets across {len(index['metadata']['libraries'])} libraries")
    return 0


if __name__ == "__main__":
    sys.exit(main())
