#!/usr/bin/env python3
"""Apply deterministic label replacements to a scaffolded .drawio file.

Mapping formats:
  {"Old visible label": "New label"}
  {"ids": {"cell-id": "New label"}, "labels": {"Old visible label": "New label"}}

Visible-label matching ignores HTML wrappers and treats <br> as whitespace.
"""
from __future__ import annotations

import argparse
import html
import json
import re
import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable


LABEL_ATTRS = ("value", "label", "name")


@dataclass(frozen=True)
class Replacement:
    element_id: str
    attr: str
    old: str
    new: str
    matched_by: str


def clean_label(value: str) -> str:
    value = html.unescape(value)
    value = re.sub(r"<br\s*/?>", " ", value, flags=re.I)
    value = re.sub(r"<[^>]+>", " ", value)
    value = value.replace("&nbsp;", " ")
    return re.sub(r"\s+", " ", value).strip()


def as_drawio_label(value: str) -> str:
    return value.replace("\r\n", "\n").replace("\r", "\n").replace("\n", "<br>")


def replace_inner_simple_html(raw: str, new_value: str) -> str:
    replacement = as_drawio_label(new_value)
    match = re.fullmatch(
        r"(?P<prefix><(?P<tag>b|i|u|font|span)\b[^>]*>)(?P<body>.*)(?P<suffix></(?P=tag)>)",
        raw,
        flags=re.I | re.S,
    )
    if match:
        return f"{match.group('prefix')}{replacement}{match.group('suffix')}"
    return replacement


def load_mapping(path: Path) -> tuple[dict[str, str], dict[str, str]]:
    data: Any = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("mapping JSON must be an object")

    if "ids" in data or "labels" in data:
        ids = data.get("ids", {})
        labels = data.get("labels", {})
        if not isinstance(ids, dict) or not isinstance(labels, dict):
            raise ValueError("'ids' and 'labels' must be objects when present")
    else:
        ids = {}
        labels = data

    id_map = {str(key): str(value) for key, value in ids.items()}
    label_map = {clean_label(str(key)): str(value) for key, value in labels.items()}
    return id_map, label_map


def relabel_tree(root: ET.Element, id_map: dict[str, str], label_map: dict[str, str]) -> list[Replacement]:
    replacements: list[Replacement] = []
    for elem in root.iter():
        elem_id = elem.get("id") or ""
        attr = next((name for name in LABEL_ATTRS if elem.get(name) is not None), None)
        if attr is None:
            continue

        raw = elem.get(attr) or ""
        matched_by = ""
        new_value: str | None = None
        if elem_id in id_map:
            new_value = id_map[elem_id]
            matched_by = f"id:{elem_id}"
        else:
            visible = clean_label(raw)
            if visible in label_map:
                new_value = label_map[visible]
                matched_by = f"label:{visible}"

        if new_value is None:
            continue

        updated = replace_inner_simple_html(raw, new_value)
        if updated == raw:
            continue
        elem.set(attr, updated)
        replacements.append(
            Replacement(
                element_id=elem_id,
                attr=attr,
                old=clean_label(raw),
                new=clean_label(updated),
                matched_by=matched_by,
            )
        )
    return replacements


def relabel_file(source: Path, mapping: Path, destination: Path | None = None) -> list[Replacement]:
    id_map, label_map = load_mapping(mapping)
    tree = ET.parse(source)
    replacements = relabel_tree(tree.getroot(), id_map, label_map)
    ET.indent(tree, space="  ")
    target = destination or source
    tree.write(target, encoding="unicode", xml_declaration=False)
    return replacements


def print_summary(replacements: Iterable[Replacement]) -> None:
    items = list(replacements)
    print(f"relabel: replaced {len(items)} label(s)", file=sys.stderr)
    for item in items:
        print(f"  {item.matched_by}: {item.old!r} -> {item.new!r}", file=sys.stderr)


def main(argv: Iterable[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("drawio", type=Path)
    ap.add_argument("mapping", type=Path, help="JSON replacement map")
    ap.add_argument("-o", "--out", type=Path, help="write to a new file")
    ap.add_argument("--write", action="store_true", help="modify the .drawio file in place")
    args = ap.parse_args(list(argv) if argv is not None else None)

    if args.out and args.write:
        print("use either --out or --write, not both", file=sys.stderr)
        return 2
    if not args.drawio.exists():
        print(f"{args.drawio}: file not found", file=sys.stderr)
        return 2
    if not args.mapping.exists():
        print(f"{args.mapping}: mapping not found", file=sys.stderr)
        return 2
    destination = args.drawio if args.write else args.out
    if destination is None:
        print("pass --write or --out", file=sys.stderr)
        return 2

    try:
        replacements = relabel_file(args.drawio, args.mapping, destination)
    except (ET.ParseError, OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"relabel failed: {exc}", file=sys.stderr)
        return 1
    print_summary(replacements)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
