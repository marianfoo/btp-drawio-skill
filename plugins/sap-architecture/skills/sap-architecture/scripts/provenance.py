#!/usr/bin/env python3
"""Mark SAP-template derivatives and audit source-specific identifiers.

The sanitizer removes detectable official reference ids, QR/link cells, and
source hyperlinks, then adds visible derivative attribution. Ambiguous embedded
square raster images fail strict audit until their hashes are explicitly allowed
after visual inspection.
"""
from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
import shutil
import sys
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Iterable


OFFICIAL_PATTERN = re.compile(
    r"(?:\bRA\d{4}\b|architecture\.learning\.sap\.com|SAP Architecture Center|official SAP reference architecture)",
    re.I,
)
QR_PATTERN = re.compile(r"(?:\bQR\b|quick response|scan (?:me|to))", re.I)
IMAGE_RE = re.compile(r"(?:^|;)image=([^;]+)")
RASTER_PREFIXES = ("data:image/png", "data:image/jpeg", "data:image/jpg")
DISCLAIMER_ID = "guarded-provenance"
DISCLAIMER_PREFIX = "Derived architecture. Modified; not an official SAP Reference Architecture."


@dataclass(frozen=True)
class ProvenanceIssue:
    code: str
    message: str
    cell_id: str = ""


@dataclass
class ProvenanceReport:
    errors: list[ProvenanceIssue] = field(default_factory=list)
    warnings: list[ProvenanceIssue] = field(default_factory=list)
    candidate_raster_hashes: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


def clean_label(value: str) -> str:
    value = html.unescape(value or "")
    value = re.sub(r"<br\s*/?>", " ", value, flags=re.I)
    value = re.sub(r"<[^>]+>", " ", value)
    return re.sub(r"\s+", " ", value.replace("&nbsp;", " ")).strip()


def image_payload(style: str) -> str:
    match = IMAGE_RE.search(style or "")
    return match.group(1) if match else ""


def raster_hash(cell: ET.Element) -> str | None:
    payload = image_payload(cell.get("style") or "")
    if not payload.lower().startswith(RASTER_PREFIXES):
        return None
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def likely_qr_candidate(cell: ET.Element) -> bool:
    if raster_hash(cell) is None or clean_label(cell.get("value") or ""):
        return False
    geometry = cell.find("mxGeometry")
    if geometry is None:
        return False
    try:
        width = float(geometry.get("width") or 0)
        height = float(geometry.get("height") or 0)
    except ValueError:
        return False
    if not (16 <= width <= 180 and 16 <= height <= 180):
        return False
    return 0.75 <= width / max(height, 1) <= 1.33


def first_graph_model(root: ET.Element) -> ET.Element:
    graph = root.find("./diagram/mxGraphModel") if root.tag == "mxfile" else root.find(".//mxGraphModel")
    if graph is None:
        raise ValueError("drawio file has no uncompressed mxGraphModel")
    return graph


def diagram_graphs(root: ET.Element) -> list[tuple[ET.Element | None, ET.Element]]:
    """Return every uncompressed page while retaining its diagram wrapper."""
    if root.tag == "mxfile":
        result = [
            (diagram, graph)
            for diagram in root.findall("diagram")
            if (graph := diagram.find("mxGraphModel")) is not None
        ]
    else:
        graph = root if root.tag == "mxGraphModel" else root.find(".//mxGraphModel")
        result = [(None, graph)] if graph is not None else []
    if not result:
        raise ValueError("drawio file has no uncompressed mxGraphModel")
    return result


def remove_element(root: ET.Element, target: ET.Element) -> None:
    for parent in root.iter():
        for child in list(parent):
            if child is target:
                parent.remove(child)
                return


def source_specific_element(elem: ET.Element) -> bool:
    combined = " ".join(elem.get(attr) or "" for attr in ("value", "label", "name", "link", "href", "tooltip"))
    role = (elem.get("data-provenance-role") or "").lower()
    is_image = "image=" in (elem.get("style") or "")
    return role in {"official-qr", "official-reference-id", "official-reference-link"} or (
        is_image and (OFFICIAL_PATTERN.search(combined) is not None or QR_PATTERN.search(combined) is not None)
    )


def drawing_layer_id(model_root: ET.Element) -> str:
    root_cell = next(
        (cell for cell in model_root.findall("mxCell") if not cell.get("parent") and cell.get("id")),
        None,
    )
    if root_cell is not None:
        layer = next(
            (
                cell for cell in model_root.findall("mxCell")
                if cell.get("parent") == root_cell.get("id") and cell.get("id")
            ),
            None,
        )
        if layer is not None:
            return layer.get("id") or "1"
    return "1"


def top_level_bounds(model_root: ET.Element, layer_id: str) -> tuple[float, float, float, float] | None:
    boxes: list[tuple[float, float, float, float]] = []
    for cell in model_root.iter("mxCell"):
        if cell.get("parent") != layer_id or cell.get("vertex") != "1":
            continue
        geometry = cell.find("mxGeometry")
        if geometry is None:
            continue
        try:
            x = float(geometry.get("x") or 0)
            y = float(geometry.get("y") or 0)
            width = float(geometry.get("width") or 0)
            height = float(geometry.get("height") or 0)
        except ValueError:
            continue
        boxes.append((x, y, x + width, y + height))
    if not boxes:
        return None
    return (
        min(box[0] for box in boxes),
        min(box[1] for box in boxes),
        max(box[2] for box in boxes),
        max(box[3] for box in boxes),
    )


def sanitize_tree(root: ET.Element, *, source_template: str, source_url: str) -> list[str]:
    removed_ids: list[str] = []
    for elem in list(root.iter()):
        if source_specific_element(elem):
            if elem.get("id"):
                removed_ids.append(elem.get("id") or "")
            remove_element(root, elem)
            continue
        for attr in ("link", "href", "tooltip"):
            raw = elem.get(attr) or ""
            if OFFICIAL_PATTERN.search(raw):
                elem.attrib.pop(attr, None)
        for attr in ("value", "label", "name"):
            raw = elem.get(attr)
            if raw and elem.get("id") != DISCLAIMER_ID and OFFICIAL_PATTERN.search(clean_label(raw)):
                updated = re.sub(r"\bRA\d{4}\b", "", raw, flags=re.I)
                updated = re.sub(r"SAP Architecture Center", "SAP-style", updated, flags=re.I)
                elem.set(attr, updated)

    removed = set(removed_ids)
    for cell in list(root.iter("mxCell")):
        if cell.get("source") in removed or cell.get("target") in removed:
            remove_element(root, cell)

    root.set("data-guarded-derivative", "true")
    root.set("data-guarded-source-template", source_template)
    root.set("data-guarded-source-url", source_url)
    root.set("data-guarded-provenance-version", "1")

    for diagram, graph in diagram_graphs(root):
        page_template = (diagram.get("data-guarded-source-template") if diagram is not None else None) or source_template
        page_url = (diagram.get("data-guarded-source-url") if diagram is not None else None) or source_url
        if diagram is not None:
            diagram.set("data-guarded-source-template", page_template)
            diagram.set("data-guarded-source-url", page_url)
        model_root = graph.find("root")
        if model_root is None:
            raise ValueError("mxGraphModel has no root")
        had_disclaimer = any(cell.get("id") == DISCLAIMER_ID for cell in model_root.iter("mxCell"))
        for cell in list(model_root.iter("mxCell")):
            if cell.get("id") == DISCLAIMER_ID:
                remove_element(model_root, cell)

        try:
            page_width = float(graph.get("pageWidth") or 1169)
            page_height = float(graph.get("pageHeight") or 827)
        except ValueError as exc:
            raise ValueError("invalid page dimensions") from exc
        new_height = page_height if had_disclaimer else page_height + 40
        graph.set("pageHeight", str(int(new_height) if new_height.is_integer() else new_height))
        layer_id = drawing_layer_id(model_root)
        bounds = top_level_bounds(model_root, layer_id)
        if bounds is None:
            disclaimer_x = 20.0
            disclaimer_y = page_height + 10
            disclaimer_width = max(100.0, page_width - 40)
        else:
            min_x, _min_y, max_x, max_y = bounds
            disclaimer_x = min_x + 20
            disclaimer_y = max_y + 10
            disclaimer_width = max(100.0, max_x - min_x - 40)
        disclaimer = ET.SubElement(
            model_root,
            "mxCell",
            {
                "id": DISCLAIMER_ID,
                "value": f"{DISCLAIMER_PREFIX} Source template: {page_template}. Source: {page_url}",
                "style": (
                    "text;html=1;strokeColor=none;fillColor=none;align=left;verticalAlign=middle;"
                    "whiteSpace=wrap;fontFamily=Helvetica;fontSize=8;fontColor=#475E75;"
                ),
                "vertex": "1",
                "parent": layer_id,
            },
        )
        ET.SubElement(
            disclaimer,
            "mxGeometry",
            {
                "x": str(int(disclaimer_x) if disclaimer_x.is_integer() else disclaimer_x),
                "y": str(int(disclaimer_y) if disclaimer_y.is_integer() else disclaimer_y),
                "width": str(int(disclaimer_width) if disclaimer_width.is_integer() else disclaimer_width),
                "height": "20",
                "as": "geometry",
            },
        )
    return removed_ids


def audit_tree(root: ET.Element, *, allowed_raster_hashes: set[str] | None = None) -> ProvenanceReport:
    allowed = allowed_raster_hashes or set()
    report = ProvenanceReport()
    if root.get("data-guarded-derivative") != "true":
        report.errors.append(ProvenanceIssue("missing-derivative-metadata", "diagram is not marked as a derivative"))
    if not root.get("data-guarded-source-template") or not root.get("data-guarded-source-url"):
        report.errors.append(ProvenanceIssue("missing-source-metadata", "source template and source URL metadata are required"))

    disclaimer_pages: set[int] = set()
    page_by_element: dict[int, int] = {}
    graphs = diagram_graphs(root)
    for page_index, (diagram, _graph) in enumerate(graphs, start=1):
        scope = diagram if diagram is not None else root
        for elem in scope.iter():
            page_by_element[id(elem)] = page_index
        if len(graphs) > 1 and diagram is not None:
            if not diagram.get("data-guarded-source-template") or not diagram.get("data-guarded-source-url"):
                report.errors.append(
                    ProvenanceIssue(
                        "missing-page-source-metadata",
                        f"diagram page {page_index} requires source template and URL metadata",
                    )
                )
    for elem in root.iter():
        elem_id = elem.get("id") or ""
        labels = " ".join(elem.get(attr) or "" for attr in ("value", "label", "name"))
        visible = clean_label(labels)
        if elem_id == DISCLAIMER_ID and visible.startswith(DISCLAIMER_PREFIX):
            disclaimer_pages.add(page_by_element.get(id(elem), 1))
        elif OFFICIAL_PATTERN.search(visible):
            report.errors.append(ProvenanceIssue("source-identifier", f"source-specific identifier remains: {visible[:120]}", elem_id))
        for attr in ("link", "href", "tooltip"):
            raw = elem.get(attr) or ""
            if OFFICIAL_PATTERN.search(raw):
                report.errors.append(ProvenanceIssue("source-link", f"source-specific {attr} remains", elem_id))
        if elem.tag == "mxCell" and likely_qr_candidate(elem):
            digest = raster_hash(elem)
            if digest:
                report.candidate_raster_hashes.append(digest)
                if digest not in allowed:
                    report.warnings.append(
                        ProvenanceIssue(
                            "unreviewed-square-raster",
                            f"embedded square raster may be a QR/reference image; visually review and allow hash {digest}",
                            elem_id,
                        )
                    )
    for page_index in range(1, len(graphs) + 1):
        if page_index not in disclaimer_pages:
            report.errors.append(
                ProvenanceIssue(
                    "missing-visible-disclaimer",
                    f"visible derivative disclaimer is required on diagram page {page_index}",
                )
            )
    report.candidate_raster_hashes = sorted(set(report.candidate_raster_hashes))
    return report


def sanitize_file(source: Path, destination: Path, *, source_template: str, source_url: str) -> list[str]:
    tree = ET.parse(source)
    removed = sanitize_tree(tree.getroot(), source_template=source_template, source_url=source_url)
    ET.indent(tree, space="  ")
    tree.write(destination, encoding="unicode", xml_declaration=False)
    return removed


def main(argv: Iterable[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("drawio", type=Path)
    ap.add_argument("--source-template")
    ap.add_argument("--source-url")
    ap.add_argument("-o", "--out", type=Path)
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--audit", action="store_true")
    ap.add_argument("--strict", action="store_true", help="fail on unresolved raster-review warnings")
    ap.add_argument("--allow-raster-hash", action="append", default=[])
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(list(argv) if argv is not None else None)
    if not args.drawio.exists():
        print(f"{args.drawio}: not found", file=sys.stderr)
        return 2
    if args.out and args.write:
        print("use either --out or --write", file=sys.stderr)
        return 2
    try:
        if not args.audit:
            if not args.source_template or not args.source_url:
                print("--source-template and --source-url are required when sanitizing", file=sys.stderr)
                return 2
            destination = args.drawio if args.write else args.out
            if destination is None:
                print("pass --write or --out", file=sys.stderr)
                return 2
            if args.write:
                shutil.copy2(args.drawio, args.drawio.with_suffix(args.drawio.suffix + ".bak"))
            removed = sanitize_file(
                args.drawio,
                destination,
                source_template=args.source_template,
                source_url=args.source_url,
            )
            print(f"provenance: marked derivative; removed {len(removed)} source-specific cell(s)", file=sys.stderr)
            target = destination
        else:
            target = args.drawio
        report = audit_tree(ET.parse(target).getroot(), allowed_raster_hashes=set(args.allow_raster_hash))
    except (ET.ParseError, OSError, ValueError) as exc:
        print(f"provenance failed: {exc}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(asdict(report), indent=2))
    else:
        for issue in report.errors:
            print(f"ERROR [{issue.code}] {issue.cell_id} {issue.message}".strip())
        for issue in report.warnings:
            print(f"WARN  [{issue.code}] {issue.cell_id} {issue.message}".strip())
        print(f"provenance audit: {len(report.errors)} error(s), {len(report.warnings)} warning(s)")
    return 1 if report.errors or (args.strict and report.warnings) else 0


if __name__ == "__main__":
    raise SystemExit(main())
