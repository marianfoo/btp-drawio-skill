#!/usr/bin/env python3
"""Compare two .drawio files and produce a similarity / divergence report.

The goal isn't pixel-perfect equality — it's to surface *structural* and *style*
divergences so an iterative loop can drive a generated diagram toward an SAP
reference. Two diagrams that draw the same scenario end up with very similar
fingerprints across these dimensions:

  Structural
    * canvas size (W × H) — should match the selected SAP template
    * total cell count, vertex count, edge count
    * zone count (cells with arcSize=16, strokeWidth=1.5, fontStyle=1, top-left
      label)
    * service-icon count (cells with shape=image and SAP icon SVG data URI)
    * pill count (small cells with arcSize=50)

  Style
    * palette (set of hex colors, Jaccard similarity)
    * fonts (set of fontFamily values)
    * stroke widths (set)
    * presence of `absoluteArcSize=1`, `labelBackgroundColor=default`
    * grid-snap rate (% of geometries on the 10-px grid)

Usage:
  compare.py reference.drawio candidate.drawio                    # human report
  compare.py --json reference.drawio candidate.drawio              # JSON report
  compare.py --score reference.drawio candidate.drawio             # one-line score 0..100

Score is a weighted blend of the dimensions above; 100 = identical fingerprint
(not necessarily identical content), 0 = nothing in common.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass, field
from pathlib import Path

HEX_RE = re.compile(r"#[0-9A-Fa-f]{6}\b")
DATA_URI_RE = re.compile(r"data:image/[^&\";]+")
ICON_RE = re.compile(r"shape=image[^\"]*image=data:image/svg|shape=mxgraph\.sap\.icon")
EXTERNAL_IMAGE_RE = re.compile(r"shape=image[^\"]*image=https?://|image=https?://")
SHAPE_RE = re.compile(r"(?:^|;)shape=([^;\"]+)")
ARC16_RE = re.compile(r"arcSize=16\b")
ARC50_RE = re.compile(r"arcSize=50\b")
ABS_ARC_RE = re.compile(r"absoluteArcSize=1\b")
LABEL_BG_RE = re.compile(r"labelBackgroundColor=default\b")
ZONE_HINT_RE = re.compile(r"strokeWidth=1\.5[^\"]*fontStyle=1|fontStyle=1[^\"]*strokeWidth=1\.5")
PILL_HINT_RE = re.compile(r"arcSize=50[^\"]*strokeWidth=1\b|strokeWidth=1\b[^\"]*arcSize=50")
FONT_RE = re.compile(r"fontFamily=([^;\"]+)")
STROKE_RE = re.compile(r"strokeWidth=([0-9.]+)")
LINE_RE = re.compile(r"^line", re.I)


# --- Fingerprint ---------------------------------------------------------------


@dataclass
class Fingerprint:
    path: str
    canvas_w: int = 0
    canvas_h: int = 0
    cells_total: int = 0
    vertices: int = 0
    edges: int = 0
    zones: int = 0
    icons: int = 0
    external_images: int = 0
    pills: int = 0
    grid_snap_rate: float = 0.0
    has_absolute_arc: bool = False
    has_label_bg: bool = False
    palette: set[str] = field(default_factory=set)
    fonts: set[str] = field(default_factory=set)
    stroke_widths: set[float] = field(default_factory=set)
    shapes: set[str] = field(default_factory=set)


def fingerprint(path: Path) -> Fingerprint:
    fp = Fingerprint(path=str(path))
    text = path.read_text(encoding="utf-8")
    palette_text = DATA_URI_RE.sub("", text)
    fp.palette = {h.upper() for h in HEX_RE.findall(palette_text)}
    fp.fonts = set(FONT_RE.findall(palette_text))
    fp.stroke_widths = {float(s) for s in STROKE_RE.findall(palette_text)}
    fp.has_absolute_arc = bool(ABS_ARC_RE.search(text))
    fp.has_label_bg = bool(LABEL_BG_RE.search(text))

    try:
        root = ET.parse(path).getroot()
    except ET.ParseError:
        return fp

    diagram = root.find(".//diagram")
    mxfile = root.find(".//mxGraphModel") if root.tag != "mxfile" else None
    graph = root.find(".//mxGraphModel")
    if graph is not None:
        fp.canvas_w = int(graph.get("pageWidth") or graph.get("dx") or 0)
        fp.canvas_h = int(graph.get("pageHeight") or graph.get("dy") or 0)

    cells = root.findall(".//mxCell")
    fp.cells_total = len(cells)
    coords: list[float] = []
    for c in cells:
        if c.get("vertex") == "1":
            fp.vertices += 1
            style = c.get("style") or ""
            if ICON_RE.search(style):
                fp.icons += 1
            if EXTERNAL_IMAGE_RE.search(style):
                fp.external_images += 1
            for shape in SHAPE_RE.findall(style):
                if shape != "image":
                    fp.shapes.add(shape)
            if ARC50_RE.search(style):
                fp.pills += 1
            elif ARC16_RE.search(style) and "strokeWidth=1.5" in style and "fontStyle=1" in style:
                fp.zones += 1
            geo = c.find("mxGeometry")
            if geo is not None:
                for attr in ("x", "y", "width", "height"):
                    v = geo.get(attr)
                    if v is not None:
                        try:
                            coords.append(float(v))
                        except ValueError:
                            pass
        elif c.get("edge") == "1":
            fp.edges += 1
    if coords:
        snapped = sum(1 for v in coords if abs(v - round(v)) < 1e-6 and round(v) % 10 == 0)
        fp.grid_snap_rate = snapped / len(coords)
    return fp


# --- Comparison ----------------------------------------------------------------


def jaccard(a: set, b: set) -> float:
    if not a and not b:
        return 1.0
    return len(a & b) / max(1, len(a | b))


@dataclass
class CompareResult:
    score: float = 0.0
    breakdown: dict = field(default_factory=dict)
    diffs: list[str] = field(default_factory=list)


def compare(ref: Fingerprint, cand: Fingerprint) -> CompareResult:
    r = CompareResult()
    parts: dict[str, float] = {}

    parts["canvas"] = 1.0 if (ref.canvas_w == cand.canvas_w and ref.canvas_h == cand.canvas_h) else 0.0
    if not parts["canvas"]:
        r.diffs.append(f"canvas mismatch — ref {ref.canvas_w}x{ref.canvas_h} vs cand {cand.canvas_w}x{cand.canvas_h}")

    def ratio(a: float, b: float) -> float:
        if a == 0 and b == 0:
            return 1.0
        if a == 0 or b == 0:
            return 0.0
        return min(a, b) / max(a, b)

    # zones: detection is unreliable across SAP files — many style strings don't
    # match our heuristic — drop from scoring unless reference has at least one
    if ref.zones > 0 or cand.zones > 0:
        parts["zones"] = ratio(ref.zones, cand.zones)
    parts["icons"] = ratio(ref.icons, cand.icons)
    parts["external_images"] = 1.0 if cand.external_images <= ref.external_images else ratio(ref.external_images, cand.external_images)
    parts["edges"] = ratio(ref.edges, cand.edges)
    parts["vertices"] = ratio(ref.vertices, cand.vertices)
    parts["pills"] = ratio(ref.pills, cand.pills) if (ref.pills or cand.pills) else 1.0

    parts["palette"] = jaccard(ref.palette, cand.palette)
    only_in_cand = cand.palette - ref.palette
    if only_in_cand:
        r.diffs.append(f"colors in candidate not in reference: {sorted(only_in_cand)[:8]}")

    # fonts: candidate ⊆ ref counts as full credit. SAP's own files mix
    # Arial+Helvetica; if our candidate uses only one of them, that's fine.
    if cand.fonts and ref.fonts and cand.fonts <= ref.fonts:
        parts["fonts"] = 1.0
    else:
        parts["fonts"] = jaccard(ref.fonts, cand.fonts)
    if cand.fonts and not (cand.fonts <= ref.fonts):
        r.diffs.append(f"fonts: ref={sorted(ref.fonts)} cand={sorted(cand.fonts)}")

    parts["strokes"] = jaccard(ref.stroke_widths, cand.stroke_widths)
    parts["shapes"] = jaccard(ref.shapes, cand.shapes)
    extra_shapes = cand.shapes - ref.shapes
    if extra_shapes:
        r.diffs.append(f"shape styles in candidate not in reference: {sorted(extra_shapes)[:8]}")
    if cand.external_images > ref.external_images:
        r.diffs.append(f"external image count increased — ref {ref.external_images} vs cand {cand.external_images}")
    parts["abs_arc"] = 1.0 if ref.has_absolute_arc == cand.has_absolute_arc else 0.5
    parts["label_bg"] = 1.0 if ref.has_label_bg == cand.has_label_bg else 0.5
    # grid_snap: candidate at-or-above reference scores 1.0; else proportional.
    # We don't penalise the candidate for being MORE snapped than SAP's own files,
    # we just want it to be at least as clean. Target absolute rate is ≥ 0.95
    # which we surface as a separate diff.
    if ref.grid_snap_rate >= 0.95:
        parts["grid_snap"] = 1.0 if cand.grid_snap_rate >= ref.grid_snap_rate * 0.95 else cand.grid_snap_rate
    else:
        # SAP reference itself is sloppy — give candidate full credit if it matches or exceeds it
        parts["grid_snap"] = 1.0 if cand.grid_snap_rate >= ref.grid_snap_rate else cand.grid_snap_rate / max(0.01, ref.grid_snap_rate)
    if cand.grid_snap_rate < 0.95:
        r.diffs.append(f"grid-snap rate {cand.grid_snap_rate*100:.1f}% (recommend 95%+; reference is {ref.grid_snap_rate*100:.1f}%)")

    weights = {
        "canvas": 1.0,
        "zones": 1.5,
        "icons": 1.5,
        "external_images": 0.5,
        "edges": 1.0,
        "vertices": 0.5,
        "pills": 0.5,
        "palette": 1.5,
        "fonts": 1.0,
        "strokes": 0.5,
        "shapes": 1.0,
        "abs_arc": 0.5,
        "label_bg": 0.5,
        "grid_snap": 1.0,
    }
    total_weight = sum(weights[k] for k in parts)
    score = sum(parts[k] * weights[k] for k in parts) / total_weight * 100
    r.score = round(score, 1)
    r.breakdown = parts
    return r


# --- CLI -----------------------------------------------------------------------


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("reference", type=Path)
    ap.add_argument("candidate", type=Path)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--score", action="store_true")
    args = ap.parse_args()

    ref = fingerprint(args.reference)
    cand = fingerprint(args.candidate)
    result = compare(ref, cand)

    if args.score:
        print(f"{result.score:.1f}")
        return 0
    if args.json:
        out = {
            "score": result.score,
            "breakdown": result.breakdown,
            "diffs": result.diffs,
            "reference": asdict(ref),
            "candidate": asdict(cand),
        }
        # sets aren't JSON-serializable; coerce
        for fp_dict in (out["reference"], out["candidate"]):
            for k in ("palette", "fonts", "stroke_widths", "shapes"):
                fp_dict[k] = sorted(fp_dict[k])
        print(json.dumps(out, indent=2))
        return 0

    print(f"reference : {args.reference}")
    print(f"candidate : {args.candidate}")
    print(f"score     : {result.score:.1f}/100")
    print("breakdown :")
    for k, v in result.breakdown.items():
        bar = "█" * int(v * 20)
        print(f"   {k:10s}  {v*100:5.1f}%  {bar}")
    if result.diffs:
        print("\nnotable diffs:")
        for d in result.diffs:
            print(f"  - {d}")
    print("\nreference fingerprint:")
    for k, v in asdict(ref).items():
        if isinstance(v, set):
            v = sorted(v)
        print(f"   {k}: {v}")
    print("\ncandidate fingerprint:")
    for k, v in asdict(cand).items():
        if isinstance(v, set):
            v = sorted(v)
        print(f"   {k}: {v}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
