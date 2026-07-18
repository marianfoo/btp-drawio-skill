#!/usr/bin/env python3
"""Export every page of a canonical multi-page .drawio file with manifests."""
from __future__ import annotations

import argparse
import copy
import csv
import hashlib
import json
import re
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Iterable

THIS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(THIS_DIR))

import render  # type: ignore[import-not-found]  # noqa: E402


SUPPORTED_FORMATS = ("svg", "png", "pdf")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def slugify(value: str) -> str:
    value = re.sub(r"[^A-Za-z0-9]+", "-", value).strip("-").lower()
    return value or "page"


def load_json(path: Path | None) -> dict[str, Any]:
    if path is None:
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"JSON input must be an object: {path}")
    return data


def export_page(
    cli: str,
    source: Path,
    destination: Path,
    *,
    fmt: str,
    page_index: int,
    scale: float,
    border: int,
    embed_diagram: bool,
) -> None:
    args = [
        cli,
        "-x",
        "-f",
        fmt,
        "-p",
        str(page_index),
        "-o",
        str(destination),
        "-s",
        str(scale),
        "-b",
        str(border),
    ]
    if embed_diagram and fmt in {"svg", "png", "pdf"}:
        args.append("-e")
    args.append(str(source))
    proc = subprocess.run(args, check=False, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=120)
    if proc.returncode != 0 or not destination.exists():
        detail = (proc.stdout + proc.stderr).decode(errors="replace").strip()
        raise RuntimeError(f"page {page_index} {fmt} export failed: {detail}")


def write_page_drawio(root: ET.Element, diagram: ET.Element, destination: Path) -> None:
    page_root = copy.deepcopy(root)
    for existing in list(page_root.findall("diagram")):
        page_root.remove(existing)
    page_root.append(copy.deepcopy(diagram))
    destination.parent.mkdir(parents=True, exist_ok=True)
    tree = ET.ElementTree(page_root)
    ET.indent(tree, space="  ")
    tree.write(destination, encoding="unicode", xml_declaration=False)


def page_spec(pack_spec: dict[str, Any], page_name: str) -> dict[str, Any]:
    pages = pack_spec.get("pages", [])
    page = next((item for item in pages if isinstance(item, dict) and item.get("name") == page_name), None)
    if page is None:
        raise ValueError(f"semantic pack spec has no page: {page_name}")
    result = {"schema_version": 1, "subject": page.get("purpose", page_name)}
    for key in (
        "level",
        "required_nodes",
        "required_zones",
        "required_terms",
        "required_flows",
        "forbidden_terms",
    ):
        result[key] = copy.deepcopy(page.get(key, [] if key != "level" else "L2"))
    result["provenance"] = copy.deepcopy(pack_spec.get("provenance", {"allowed_raster_hashes": []}))
    return result


def export_pack(
    source: Path,
    out_dir: Path,
    *,
    formats: tuple[str, ...],
    scale: float,
    border: int,
    embed_diagram: bool,
    spec_path: Path | None,
    targets_path: Path | None,
    emit_page_drawio: bool,
) -> dict[str, Any]:
    cli = render.find_drawio_cli()
    if not cli:
        raise RuntimeError("draw.io CLI unavailable")
    tree = ET.parse(source)
    root = tree.getroot()
    if root.tag != "mxfile":
        raise ValueError("pack export requires an mxfile")
    diagrams = root.findall("diagram")
    if not diagrams:
        raise ValueError("pack contains no pages")
    spec = load_json(spec_path)
    targets = load_json(targets_path)
    targets_by_name = {
        str(item.get("page_name")): item
        for item in targets.get("pages", [])
        if isinstance(item, dict)
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, Any]] = []
    for page_index, diagram in enumerate(diagrams, start=1):
        page_name = diagram.get("name") or f"Page {page_index}"
        stem = f"{page_index:02d}--{slugify(page_name)}"
        row: dict[str, Any] = {
            "page_index": page_index,
            "page_name": page_name,
            "source_template": targets_by_name.get(page_name, {}).get("template", ""),
            "source_template_sha256": targets_by_name.get(page_name, {}).get("template_sha256", ""),
        }
        for fmt in formats:
            destination = out_dir / fmt / f"{stem}.{fmt}"
            destination.parent.mkdir(parents=True, exist_ok=True)
            export_page(
                cli,
                source,
                destination,
                fmt=fmt,
                page_index=page_index,
                scale=scale,
                border=border,
                embed_diagram=embed_diagram,
            )
            row[fmt] = str(destination.relative_to(out_dir))
            row[f"{fmt}_sha256"] = sha256(destination)
        if emit_page_drawio:
            page_drawio = out_dir / "pages" / f"{stem}.drawio"
            write_page_drawio(root, diagram, page_drawio)
            row["page_drawio"] = str(page_drawio.relative_to(out_dir))
            row["page_drawio_sha256"] = sha256(page_drawio)
            if spec:
                spec_out = out_dir / "pages" / f"{stem}.spec.json"
                spec_out.write_text(json.dumps(page_spec(spec, page_name), indent=2) + "\n", encoding="utf-8")
                row["page_spec"] = str(spec_out.relative_to(out_dir))
                row["page_spec_sha256"] = sha256(spec_out)
        rows.append(row)

    fields = [
        "page_index",
        "page_name",
        "source_template",
        "source_template_sha256",
        *[key for fmt in formats for key in (fmt, f"{fmt}_sha256")],
    ]
    if emit_page_drawio:
        fields.extend(("page_drawio", "page_drawio_sha256"))
        if spec:
            fields.extend(("page_spec", "page_spec_sha256"))
    csv_path = out_dir / "export-manifest.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    payload = {
        "schema_version": 1,
        "canonical_drawio": str(source.resolve()),
        "canonical_drawio_sha256": sha256(source),
        "canonical_rule": ".drawio is canonical; exported files are generated derivatives and must not be edited independently.",
        "drawio_cli": cli,
        "formats": list(formats),
        "embedded_diagram": embed_diagram,
        "pages": rows,
        "csv_manifest": str(csv_path.resolve()),
    }
    json_path = out_dir / "export-manifest.json"
    json_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    payload["json_manifest"] = str(json_path.resolve())
    return payload


def main(argv: Iterable[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("drawio", type=Path)
    ap.add_argument("--out-dir", type=Path, required=True)
    ap.add_argument("--formats", default="svg,png,pdf")
    ap.add_argument("--scale", type=float, default=1.5)
    ap.add_argument("--border", type=int, default=10)
    ap.add_argument("--embed-diagram", action="store_true")
    ap.add_argument("--spec", type=Path)
    ap.add_argument("--targets", type=Path)
    ap.add_argument("--emit-page-drawio", action="store_true")
    args = ap.parse_args(list(argv) if argv is not None else None)
    if not args.drawio.exists() or (args.spec and not args.spec.exists()) or (args.targets and not args.targets.exists()):
        print("drawio, spec, and target inputs must exist", file=sys.stderr)
        return 2
    formats = tuple(item.strip().lower() for item in args.formats.split(",") if item.strip())
    if not formats or any(fmt not in SUPPORTED_FORMATS for fmt in formats):
        print(f"formats must be selected from: {', '.join(SUPPORTED_FORMATS)}", file=sys.stderr)
        return 2
    try:
        result = export_pack(
            args.drawio,
            args.out_dir,
            formats=formats,
            scale=args.scale,
            border=args.border,
            embed_diagram=args.embed_diagram,
            spec_path=args.spec,
            targets_path=args.targets,
            emit_page_drawio=args.emit_page_drawio,
        )
    except (ET.ParseError, OSError, ValueError, RuntimeError, json.JSONDecodeError, subprocess.TimeoutExpired) as exc:
        print(f"pack export failed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
