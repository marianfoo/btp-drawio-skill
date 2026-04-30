#!/usr/bin/env python3
"""Extract a ready-to-paste mxCell snippet from any bundled SAP draw.io asset.

Examples:
  extract_asset.py --list --kind connector
  extract_asset.py "direct one-directional" --kind connector --id flow1 --x 100 --y 200
  extract_asset.py "database non sap" --kind generic-icon --id db1 --x 300 --y 160
"""
from __future__ import annotations

import argparse
import copy
import json
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape, unescape

HERE = Path(__file__).resolve().parent
ASSETS = HERE.parent / "assets"
INDEX = ASSETS / "asset-index.json"
LIB_DIR = ASSETS / "libraries"


def load_index() -> dict[str, Any]:
    if not INDEX.exists():
        print(f"asset index not found at {INDEX}; run build_asset_index.py first", file=sys.stderr)
        sys.exit(1)
    return json.loads(INDEX.read_text(encoding="utf-8"))


def load_library_entry(entry: dict[str, Any]) -> dict[str, Any]:
    path = LIB_DIR / entry["library"]
    raw = path.read_text(encoding="utf-8")
    raw = re.sub(r"<!--.*?-->", "", raw, flags=re.S).strip()
    body = raw[len("<mxlibrary>") : -len("</mxlibrary>")].strip()
    return json.loads(body)[entry["entry"]]


def normalize(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


def slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def tokens(text: str) -> set[str]:
    return {token for token in normalize(text).split() if token}


def find_asset(index: dict[str, Any], query: str, kind: str | None) -> tuple[str, dict[str, Any]] | None:
    assets = index["assets"]
    query_raw = query.strip()
    query_slug = slugify(query)
    query_tokens = tokens(query)

    filtered = [
        (key, asset)
        for key, asset in assets.items()
        if kind is None or asset["kind"] == kind
    ]

    for key, asset in filtered:
        key_short = key.split(":", 1)[-1]
        if (
            query_raw == key
            or query_raw == key_short
            or query_slug == slugify(key)
            or query_slug == slugify(key_short)
        ):
            return key, asset
        if query_slug in {slugify(alias) for alias in asset.get("aliases", [])}:
            return key, asset

    candidates: list[tuple[int, str, dict[str, Any]]] = []
    for key, asset in filtered:
        pool = tokens(key) | tokens(asset["display"]) | tokens(asset.get("title", ""))
        for alias in asset.get("aliases", []):
            pool |= tokens(alias)
        if query_tokens and query_tokens <= pool:
            candidates.append((len(pool), key, asset))

    if len(candidates) == 1:
        _, key, asset = candidates[0]
        return key, asset
    if len(candidates) > 1:
        candidates.sort(key=lambda item: (item[0], item[1]))
        top = candidates[0]
        if len(candidates) == 1 or top[0] < candidates[1][0]:
            return top[1], top[2]
        print(f"ambiguous '{query}' — {len(candidates)} matches:", file=sys.stderr)
        for _, key, asset in candidates[:12]:
            print(f"  {key} — {asset['display']}", file=sys.stderr)
        sys.exit(2)

    substring = [
        (key, asset)
        for key, asset in filtered
        if normalize(query) in normalize(asset["display"]) or query_slug in key
    ]
    if len(substring) == 1:
        return substring[0]
    if len(substring) > 1:
        print(f"ambiguous '{query}' — {len(substring)} matches:", file=sys.stderr)
        for key, asset in substring[:12]:
            print(f"  {key} — {asset['display']}", file=sys.stderr)
        sys.exit(2)
    return None


def snap(value: float) -> int:
    return round(value / 10) * 10


def mxcell_for_data(asset: dict[str, Any], library_entry: dict[str, Any], args: argparse.Namespace) -> str:
    width = snap(args.w if args.w is not None else int(asset.get("width") or 40))
    height = snap(args.h if args.h is not None else int(asset.get("height") or 40))
    label = args.label if args.label is not None else asset["display"]
    label_xml = escape(label, {'"': "&quot;"})
    style = (
        "shape=image;verticalLabelPosition=bottom;verticalAlign=top;aspect=fixed;"
        f"imageAspect=0;image={library_entry['data']};"
    )
    return (
        f'<mxCell id="{args.id}" value="{label_xml}" style="{style}" '
        f'vertex="1" parent="{args.parent}">'
        f'<mxGeometry x="{snap(args.x)}" y="{snap(args.y)}" width="{width}" height="{height}" as="geometry"/>'
        "</mxCell>"
    )


def set_edge_points(cell: ET.Element, x: int, y: int, width: int, height: int) -> None:
    geom = cell.find("mxGeometry")
    if geom is None:
        return
    source = geom.find("mxPoint[@as='sourcePoint']")
    target = geom.find("mxPoint[@as='targetPoint']")
    if source is not None:
        source.set("x", str(x))
        source.set("y", str(y))
    if target is not None:
        target.set("x", str(x + width))
        target.set("y", str(y + height))


def mx_cells_for_xml(asset: dict[str, Any], library_entry: dict[str, Any], args: argparse.Namespace) -> str:
    root = ET.fromstring(unescape(library_entry["xml"]))
    cells = [copy.deepcopy(c) for c in root.iter("mxCell") if c.get("id") not in {"0", "1"}]
    if not cells:
        raise ValueError(f"{asset['display']} contains no extractable mxCell")

    id_map: dict[str, str] = {}
    for index, cell in enumerate(cells):
        old_id = cell.get("id")
        if old_id:
            id_map[old_id] = args.id if index == 0 else f"{args.id}-{index + 1}"

    original_top_ids = {cell.get("id") for cell in cells if cell.get("parent") == "1"}
    x = snap(args.x)
    y = snap(args.y)
    width = snap(args.w) if args.w is not None else snap(int(asset.get("width") or 120))
    height = snap(args.h) if args.h is not None else 0

    for cell in cells:
        old_id = cell.get("id")
        old_parent = cell.get("parent")
        if old_id in id_map:
            cell.set("id", id_map[old_id])
        if old_parent == "1":
            cell.set("parent", args.parent)
        elif old_parent in id_map:
            cell.set("parent", id_map[old_parent])
        for ref in ("source", "target"):
            if cell.get(ref) in id_map:
                cell.set(ref, id_map[cell.get(ref)])

        if args.label is not None and old_id in original_top_ids:
            cell.set("value", escape(args.label, {'"': "&quot;"}))

        geom = cell.find("mxGeometry")
        if geom is not None and old_id in original_top_ids and cell.get("vertex") == "1":
            geom.set("x", str(x))
            geom.set("y", str(y))
            if args.w is not None:
                geom.set("width", str(width))
            if args.h is not None:
                geom.set("height", str(snap(args.h)))
        if cell.get("edge") == "1" and old_id in original_top_ids:
            set_edge_points(cell, x, y, width, height)

    return "\n".join(ET.tostring(cell, encoding="unicode") for cell in cells)


def emit_asset(asset: dict[str, Any], args: argparse.Namespace) -> str:
    library_entry = load_library_entry(asset)
    if "data" in library_entry:
        return mxcell_for_data(asset, library_entry, args)
    if "xml" in library_entry:
        return mx_cells_for_xml(asset, library_entry, args)
    raise ValueError(f"unsupported library entry for {asset['display']}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("query", nargs="?")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--kind", help="Filter by asset kind, e.g. btp-service-icon, generic-icon, connector")
    ap.add_argument("--x", type=int, default=0)
    ap.add_argument("--y", type=int, default=0)
    ap.add_argument("--w", type=int)
    ap.add_argument("--h", type=int)
    ap.add_argument("--id", default="asset1")
    ap.add_argument("--parent", default="1")
    ap.add_argument("--label")
    args = ap.parse_args()

    index = load_index()
    assets = index["assets"]
    if args.list:
        for key, asset in assets.items():
            if args.kind and asset["kind"] != args.kind:
                continue
            print(f"{key:70s} {asset['display']}")
        return 0
    if not args.query:
        ap.print_usage(sys.stderr)
        return 2

    match = find_asset(index, args.query, args.kind)
    if not match:
        print(f"no asset matches '{args.query}'", file=sys.stderr)
        return 1
    key, asset = match
    print(emit_asset(asset, args))
    print(f"# matched: {key} — {asset['display']}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
