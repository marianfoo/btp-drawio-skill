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
import html
import json
import re
import sys
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass, field
from pathlib import Path

HEX_RE = re.compile(r"#[0-9A-Fa-f]{6}\b")
DATA_URI_RE = re.compile(r"data:image/[^&\";]+")
INLINE_SVG_ICON_RE = re.compile(r"shape=image[^\"]*image=data:image/svg")
STENCIL_ICON_RE = re.compile(r"shape=mxgraph\.sap\.icon")
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
PAGE_BG_RE = re.compile(r'(?:background|pageBackgroundColor)="([^"]+)"')

# Canonical SAP flow-pill vocabulary, kept in sync with validate.py.
CANONICAL_PILL_VOCAB = {
    "trust", "authenticate", "authentication", "authorization",
    "identity", "identity lifecycle", "customer-managed identity lifecycle",
    "user", "usergroup", "group", "role", "role collection", "role collections",
    "policy", "scim", "saml2/oidc", "oidc", "saml", "openid",
    "https", "https/active", "https/standby", "rest", "rest/spi",
    "rest/token", "rest / odata", "odata/rest", "odata/rest/soap",
    "destination", "source", "target", "harmonized api",
    "data federation", "data sync", "task data",
    "a2a", "mcp", "ord",
    "business data cloud", "business role", "cdm",
    "role replica", "data", "metadata",
}
STOPWORDS = {
    "a", "an", "and", "app", "apps", "architecture", "as", "at", "be", "by",
    "cloud", "create", "diagram", "for", "from", "in", "into", "is", "l0",
    "l1", "l2", "of", "on", "or", "page", "ref", "reference", "sap", "show",
    "solution", "style", "the", "to", "use", "using", "via", "with",
}
TOKEN_CANONICAL = {
    "adminstrator": "administrator",
    "plaforms": "platforms",
    "provisoning": "provisioning",
}


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
    icons_inline: int = 0       # bundled inline-SVG icons (preferred)
    icons_stencil: int = 0      # mxgraph.sap.icon stencil legacy
    external_images: int = 0
    pills: int = 0
    grid_snap_rate: float = 0.0
    has_absolute_arc: bool = False
    has_label_bg: bool = False
    palette: set[str] = field(default_factory=set)
    edge_palette: set[str] = field(default_factory=set)  # strokeColors used on edges
    fonts: set[str] = field(default_factory=set)
    stroke_widths: set[float] = field(default_factory=set)
    shapes: set[str] = field(default_factory=set)
    label_count: int = 0
    label_tokens: set[str] = field(default_factory=set)
    pill_vocab: set[str] = field(default_factory=set)
    canonical_pill_count: int = 0
    novelty_pill_count: int = 0
    page_background: str = ""
    zone_depth: int = 0          # max nested zone depth observed
    sap_logo_count: int = 0


def split_words(text: str) -> list[str]:
    text = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1 \2", text)
    text = re.sub(r"([a-z])([A-Z])", r"\1 \2", text)
    text = text.replace("_", " ").replace("-", " ").replace("/", " ")
    return [t.lower() for t in re.findall(r"[A-Za-z0-9]+", text)]


def clean_label(value: str) -> str:
    value = html.unescape(value)
    value = re.sub(r"<br\s*/?>", " ", value, flags=re.I)
    value = re.sub(r"<[^>]+>", " ", value)
    value = re.sub(r"&nbsp;", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def tokens(text: str) -> set[str]:
    out: set[str] = set()
    words = split_words(text)
    joined = "".join(words)
    for word in words:
        word = TOKEN_CANONICAL.get(word, word)
        if len(word) >= 2 and word not in STOPWORDS:
            out.add(word)
    for compact in ("xsuaa", "privatelink", "workzone", "eventmesh", "multiaz", "multiregion", "businessdatacloud"):
        if compact in joined:
            out.add(compact)
    if "businessdatacloud" in out:
        out.add("bdc")
    if "cloudconnector" in joined:
        out.add("cloudconnector")
    if "principalpropagation" in joined:
        out.add("principalpropagation")
    if "s4hana" in joined or "4hana" in out:
        out.add("s4hana")
    return out


def parse_style_dict(style: str) -> dict[str, str]:
    out: dict[str, str] = {}
    if not style:
        return out
    for part in style.split(";"):
        part = part.strip()
        if not part or "=" not in part:
            continue
        k, v = part.split("=", 1)
        out[k.strip()] = v.strip()
    return out


def fingerprint(path: Path) -> Fingerprint:
    fp = Fingerprint(path=str(path))
    text = path.read_text(encoding="utf-8")
    palette_text = DATA_URI_RE.sub("", text)
    fp.palette = {h.upper() for h in HEX_RE.findall(palette_text)}
    fp.fonts = set(FONT_RE.findall(palette_text))
    fp.stroke_widths = {float(s) for s in STROKE_RE.findall(palette_text)}
    fp.has_absolute_arc = bool(ABS_ARC_RE.search(text))
    fp.has_label_bg = bool(LABEL_BG_RE.search(text))
    bg_match = PAGE_BG_RE.search(palette_text)
    if bg_match:
        fp.page_background = bg_match.group(1).strip().lower()

    try:
        root = ET.parse(path).getroot()
    except ET.ParseError:
        return fp

    graph = root.find(".//mxGraphModel")
    if graph is not None:
        fp.canvas_w = int(graph.get("pageWidth") or graph.get("dx") or 0)
        fp.canvas_h = int(graph.get("pageHeight") or graph.get("dy") or 0)
        if not fp.page_background:
            bg = (graph.get("background") or graph.get("pageBackgroundColor") or "").strip().lower()
            if bg:
                fp.page_background = bg

    cells = root.findall(".//mxCell")
    fp.cells_total = len(cells)
    coords: list[float] = []
    labels: set[str] = set()
    for elem in root.iter():
        for attr in ("name", "label", "value"):
            raw = elem.get(attr)
            if not raw:
                continue
            label = clean_label(raw)
            if label:
                labels.add(label)
    fp.label_count = len(labels)
    for label in labels:
        fp.label_tokens |= tokens(label)

    # Map cell id → cell so we can compute parent-zone nesting depth.
    cells_by_id: dict[str, ET.Element] = {}
    for c in cells:
        cid = c.get("id")
        if cid:
            cells_by_id[cid] = c

    parent_by_elem = {id(child): parent for parent in root.iter() for child in list(parent)}

    def is_zone_cell(c: ET.Element) -> bool:
        style_text = c.get("style") or ""
        if not ARC16_RE.search(style_text):
            return False
        if "strokeWidth=1.5" not in style_text:
            return False
        # SAP zone styling encodes bold via inline HTML in `value`, not fontStyle.
        # So we accept zone cells with arcSize=16 + strokeWidth=1.5 even without
        # fontStyle=1 — a critical fix for accurate zone counting.
        return True

    zone_ids: set[str] = set()
    for c in cells:
        if c.get("vertex") == "1":
            fp.vertices += 1
            style = c.get("style") or ""
            sd = parse_style_dict(style)
            inline_icon = bool(INLINE_SVG_ICON_RE.search(style))
            stencil_icon = bool(STENCIL_ICON_RE.search(style))
            if inline_icon:
                fp.icons += 1
                fp.icons_inline += 1
            elif stencil_icon:
                fp.icons += 1
                fp.icons_stencil += 1
            if EXTERNAL_IMAGE_RE.search(style):
                fp.external_images += 1
            image = sd.get("image", "")
            if image and "sap_logo" in image.lower():
                fp.sap_logo_count += 1
            for shape in SHAPE_RE.findall(style):
                if shape != "image":
                    fp.shapes.add(shape)
            if ARC50_RE.search(style):
                fp.pills += 1
                # capture pill label vocabulary
                raw_label = c.get("value") or ""
                if not raw_label:
                    parent = parent_by_elem.get(id(c))
                    if parent is not None and parent.tag == "UserObject":
                        raw_label = parent.get("value") or parent.get("label") or ""
                pill_label = clean_label(raw_label).strip().lower()
                if pill_label:
                    fp.pill_vocab.add(pill_label)
                    if pill_label in CANONICAL_PILL_VOCAB:
                        fp.canonical_pill_count += 1
                    else:
                        fp.novelty_pill_count += 1
            elif is_zone_cell(c):
                fp.zones += 1
                cid = c.get("id")
                if cid:
                    zone_ids.add(cid)
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
            style = c.get("style") or ""
            sd = parse_style_dict(style)
            stroke = sd.get("strokeColor", "").upper()
            if stroke and stroke.startswith("#"):
                fp.edge_palette.add(stroke)

    # Zone nesting depth: count how many zone cells appear in the parent chain.
    def zone_depth_for(c: ET.Element) -> int:
        depth = 0
        parent_id = c.get("parent")
        seen = set()
        while parent_id and parent_id not in seen:
            seen.add(parent_id)
            parent_cell = cells_by_id.get(parent_id)
            if parent_cell is None:
                break
            if parent_cell.get("id") in zone_ids:
                depth += 1
            parent_id = parent_cell.get("parent")
        return depth

    if zone_ids:
        max_depth = 0
        for c in cells:
            if c.get("vertex") != "1":
                continue
            d = zone_depth_for(c)
            if d > max_depth:
                max_depth = d
        fp.zone_depth = max_depth

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

    # Page background fidelity. SAP diagrams use white/transparent canvas;
    # any explicit non-white background is a major red flag.
    accepted_bgs = {"", "none", "default", "#ffffff", "#fff"}
    cand_bg = cand.page_background.lower()
    ref_bg = ref.page_background.lower()
    if cand_bg in accepted_bgs:
        parts["page_bg"] = 1.0
    elif cand_bg == ref_bg:
        parts["page_bg"] = 1.0
    else:
        parts["page_bg"] = 0.0
        r.diffs.append(
            f"non-white page background {cand.page_background!r} — SAP uses white/transparent canvas"
        )

    def ratio(a: float, b: float) -> float:
        if a == 0 and b == 0:
            return 1.0
        if a == 0 or b == 0:
            return 0.0
        return min(a, b) / max(a, b)

    # zones: zone detection now uses arcSize=16 + strokeWidth=1.5 (no fontStyle
    # requirement) — matches SAP's actual encoding where bold is HTML-inline.
    if ref.zones > 0 or cand.zones > 0:
        parts["zones"] = ratio(ref.zones, cand.zones)

    # zone nesting depth — matters for templates like Joule-inside-vs-beside-BTP
    if ref.zone_depth > 0 or cand.zone_depth > 0:
        parts["zone_depth"] = ratio(ref.zone_depth, cand.zone_depth)
        if ref.zone_depth != cand.zone_depth:
            r.diffs.append(
                f"zone nesting depth differs — ref {ref.zone_depth} vs cand {cand.zone_depth}"
            )

    # icons: prefer inline-SVG over legacy mxgraph.sap.icon stencils. SAP's own
    # corpus uses both, so we don't penalize stencils outright; we just count
    # inline + stencil together to match SAP's behavior.
    parts["icons"] = ratio(ref.icons, cand.icons)
    parts["external_images"] = 1.0 if cand.external_images <= ref.external_images else ratio(ref.external_images, cand.external_images)
    parts["edges"] = ratio(ref.edges, cand.edges)
    parts["vertices"] = ratio(ref.vertices, cand.vertices)
    parts["pills"] = ratio(ref.pills, cand.pills) if (ref.pills or cand.pills) else 1.0

    # Pill vocabulary fidelity. Reward use of SAP-canonical pill labels;
    # penalize candidates whose pills are mostly novelty verbs.
    if ref.pills > 0 or cand.pills > 0:
        ref_canon_rate = ref.canonical_pill_count / max(1, ref.pills)
        cand_canon_rate = cand.canonical_pill_count / max(1, cand.pills)
        if ref.pills == 0:
            parts["pill_vocab"] = 1.0 if cand_canon_rate >= 0.6 else cand_canon_rate
        else:
            # Match the reference's canon rate within tolerance, full credit if cand >= ref
            target = max(ref_canon_rate, 0.5)
            parts["pill_vocab"] = 1.0 if cand_canon_rate >= target else (cand_canon_rate / max(0.01, target))
        if cand.novelty_pill_count > 0 and cand.novelty_pill_count > ref.novelty_pill_count:
            r.diffs.append(
                f"novelty pill labels: {cand.novelty_pill_count} (cand) vs {ref.novelty_pill_count} (ref) "
                "— prefer canonical SAP verbs (TRUST/Authenticate/A2A/MCP/ORD/...)"
            )

    # Edge palette: which colors are actually used on edges? This catches
    # green↔magenta semantic swaps that the global palette set hides.
    if ref.edge_palette or cand.edge_palette:
        parts["edge_palette"] = jaccard(ref.edge_palette, cand.edge_palette)
        edge_diff = ref.edge_palette - cand.edge_palette
        if edge_diff:
            r.diffs.append(f"edge stroke colors missing from candidate: {sorted(edge_diff)[:6]}")

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
    parts["label_count"] = ratio(ref.label_count, cand.label_count)
    parts["label_tokens"] = jaccard(ref.label_tokens, cand.label_tokens)
    missing_label_tokens = ref.label_tokens - cand.label_tokens
    extra_label_tokens = cand.label_tokens - ref.label_tokens
    if parts["label_tokens"] < 0.8:
        r.diffs.append(
            "label token drift — "
            f"missing={sorted(missing_label_tokens)[:8]} extra={sorted(extra_label_tokens)[:8]}"
        )
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
        "page_bg": 1.5,            # NEW: dark/branded canvas now penalized
        "zones": 1.5,
        "zone_depth": 1.0,         # NEW: nesting hierarchy match (Joule-in-BTP bug)
        "icons": 1.5,
        "external_images": 0.5,
        "edges": 1.0,
        "vertices": 0.5,
        "pills": 0.5,
        "pill_vocab": 1.5,         # NEW: canonical SAP pill verbs vs novelty
        "palette": 1.5,
        "edge_palette": 1.0,       # NEW: connector colors actually used on edges
        "fonts": 1.0,
        "strokes": 0.5,
        "shapes": 1.0,
        "label_count": 0.5,
        "label_tokens": 2.0,
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
            for k in ("palette", "edge_palette", "fonts", "stroke_widths", "shapes", "label_tokens", "pill_vocab"):
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
