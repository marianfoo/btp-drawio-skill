#!/usr/bin/env python3
"""Extract a deep structural design profile from one .drawio file.

The fingerprint in compare.py is a similarity signature — good for scoring
but useless for *teaching* an LLM what makes a SAP template work. This
script produces a much richer per-template profile: zone inventory, card
inventory, icon size+library breakdown, pill vocabulary, edge
anchor/orthogonality stats, color usage, and detected layout patterns
(vertical network divider, identity-anchor-bottom-center, cloud-solutions
horizontal band, etc.).

When the LLM has chosen a SAP template via scaffold_diagram.py, it should
read this profile to understand the "design recipe" it's editing. The
recipe answers:

  - How many zones, of what colors, in what arrangement?
  - How many cards inside each zone?
  - What sizes are the icons (so don't override default to 80×80)?
  - What pill verbs does this scenario use?
  - What edge styles are typical here (orthogonal vs straight, anchored vs naked)?
  - What named layout patterns does this template exhibit?

Usage:
  profile_template.py <file>.drawio                 # human-readable profile
  profile_template.py <file>.drawio --json          # machine-readable
  profile_template.py --build-registry [--out FILE] # scan all bundled SAP refs and write
                                                     a single profiles.json registry

The registry is what `iterate.py` and `find_pattern.py` consult — it's
small (~250 KB for 71 templates) and shipped with the plugin.
"""
from __future__ import annotations

import argparse
import html
import json
import re
import sys
import xml.etree.ElementTree as ET
from collections import Counter
from dataclasses import asdict, dataclass, field
from pathlib import Path

THIS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(THIS_DIR))

import select_reference as _sel  # noqa: E402  for metadata lookup


HEX_RE = re.compile(r"#[0-9A-Fa-f]{6}\b")
DATA_URI_RE = re.compile(r"data:image/[^&\";]+")
SHAPE_RE = re.compile(r"(?:^|;)shape=([^;\"]+)")


# ---- Color → human name mapping (for the "zone colors" line in profiles)
COLOR_NAMES = {
    "#0070F2": "SAP blue (border)",
    "#EBF8FF": "SAP blue (fill)",
    "#475E75": "non-SAP slate (border)",
    "#F5F6F7": "non-SAP slate (fill)",
    "#188918": "positive green (border)",
    "#F5FAE5": "positive green (fill)",
    "#C35500": "critical orange (border)",
    "#FFF8D6": "critical orange (fill)",
    "#D20A0A": "negative red (border)",
    "#FFEAF4": "negative red (fill)",
    "#5D36FF": "indigo accent (border)",
    "#F1ECFF": "indigo accent (fill, Joule purple)",
    "#CC00DC": "pink accent (trust)",
    "#FFF0FA": "pink accent (fill)",
    "#07838F": "teal accent (border, MCP)",
    "#DAFDF5": "teal accent (fill)",
    "#1D2D3E": "title text",
    "#556B82": "body text",
    "#1A2733": "near-black navy",
    "#5B738B": "lighter slate",
}


@dataclass
class ZoneInfo:
    cell_id: str
    label: str
    fill: str
    stroke: str
    x: int
    y: int
    w: int
    h: int
    parent_id: str | None
    color_role: str  # "sap-blue" | "non-sap-slate" | "indigo" | "teal" | "pink" | "other"


@dataclass
class CardInfo:
    cell_id: str
    label: str
    fill: str
    stroke: str
    x: int
    y: int
    w: int
    h: int
    parent_zone: str | None


@dataclass
class IconInfo:
    cell_id: str
    library_name: str  # SAP service slug, "mxgraph.sap.icon", or "image"
    label: str
    w: int
    h: int
    parent_id: str | None


@dataclass
class PillInfo:
    cell_id: str
    label: str
    fill: str
    stroke: str


@dataclass
class EdgeInfo:
    cell_id: str
    source: str
    target: str
    stroke_color: str
    has_anchors: bool
    is_orthogonal: bool
    is_dashed: bool


@dataclass
class TemplateProfile:
    file: str
    name: str
    family: str
    level: str
    primary: bool
    title: str
    aliases: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    domain: str = ""
    canvas_w: int = 0
    canvas_h: int = 0
    background: str = ""
    zones: list[ZoneInfo] = field(default_factory=list)
    cards: list[CardInfo] = field(default_factory=list)
    icons: list[IconInfo] = field(default_factory=list)
    pills: list[PillInfo] = field(default_factory=list)
    edges: list[EdgeInfo] = field(default_factory=list)
    icon_sizes: dict[str, int] = field(default_factory=dict)  # "32x32" → count
    pill_vocab: list[str] = field(default_factory=list)
    color_distribution: dict[str, int] = field(default_factory=dict)  # hex → count
    font_sizes: dict[str, int] = field(default_factory=dict)
    fonts: list[str] = field(default_factory=list)
    edge_color_distribution: dict[str, int] = field(default_factory=dict)
    structure_summary: dict[str, int] = field(default_factory=dict)
    edge_quality: dict[str, int] = field(default_factory=dict)
    detected_patterns: list[str] = field(default_factory=list)
    description: str = ""

    def to_dict(self) -> dict:
        d = asdict(self)
        return d


# ---------- Helpers -----------------------------------------------------------

def _strip_label(raw: str) -> str:
    s = html.unescape(raw or "")
    s = re.sub(r"<br\s*/?>", " ", s, flags=re.I)
    s = re.sub(r"<[^>]+>", "", s)
    s = re.sub(r"&nbsp;", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def _parse_style(style: str | None) -> dict[str, str]:
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


def _color_role(stroke: str) -> str:
    s = stroke.upper()
    if s == "#0070F2":
        return "sap-blue"
    if s == "#475E75":
        return "non-sap-slate"
    if s == "#5D36FF":
        return "indigo (Joule purple)"
    if s == "#07838F":
        return "teal accent"
    if s == "#CC00DC":
        return "pink accent (trust)"
    if s == "#188918":
        return "positive green"
    if s == "#C35500":
        return "critical orange"
    if s == "#D20A0A":
        return "negative red"
    return f"other ({stroke})"


def _icon_library_name(style: str) -> str:
    """Extract a usable library / service name from an icon's style string."""
    if "mxgraph.sap.icon" in style:
        m = re.search(r"SAPIcon=([A-Za-z0-9_]+)", style)
        if m:
            return f"mxgraph.sap.icon/{m.group(1)}"
        return "mxgraph.sap.icon"
    # Inline-SVG icons sometimes carry an SAP-set hint in image-data URI; we can't easily
    # decode the content, but we can flag image vs not.
    if "shape=image" in style:
        return "inline-svg"
    return "unknown"


# ---------- Pattern detectors ------------------------------------------------

def _detect_patterns(profile: TemplateProfile) -> list[str]:
    """Heuristic detectors for common SAP layout patterns.

    These run on the populated profile and produce short, grep-able pattern
    tags the LLM can match against.
    """
    patterns: list[str] = []

    # Tri-zone Joule/BTP/3rd-party (RA0029 family signature)
    has_joule_color = any("indigo" in z.color_role for z in profile.zones)
    has_btp_color = any("sap-blue" in z.color_role for z in profile.zones if z.parent_id == "1")
    has_slate = any("non-sap-slate" in z.color_role for z in profile.zones if z.parent_id == "1")
    if has_joule_color and has_btp_color and has_slate:
        patterns.append("tri-zone-joule-btp-third-party")

    # Network divider — vertical bar, slate, very tall, very narrow
    for c in profile.cards:
        if c.h > 200 and c.w < 20 and "475E75" in (c.stroke + c.fill).upper():
            patterns.append("vertical-network-divider")
            break

    # Cloud Solutions horizontal band — wide BTP-blue zone at bottom containing 4+ cards
    btp_blue_zones = [z for z in profile.zones if z.color_role == "sap-blue"]
    for z in btp_blue_zones:
        if z.w > 400 and z.h < 250 and z.y > profile.canvas_h * 0.55:
            children_count = sum(1 for c in profile.cards if c.parent_zone == z.cell_id)
            if children_count >= 3:
                patterns.append("cloud-solutions-bottom-band")
                break

    # Identity anchored at bottom center (IAS icon near bottom-center)
    canvas_cx = profile.canvas_w / 2
    for icon in profile.icons:
        if "Identity" in (icon.library_name or "") or "identity" in icon.label.lower() or "ias" in icon.label.lower():
            if abs((icon.parent_id and 0 or 0) + 0) < 0:  # placeholder; check coordinates instead
                pass
            # Find geometry for this icon
            # (icon doesn't carry geometry directly; would need separate lookup;
            #  approximation: if any icon's label contains "identity"/"ias" we tag it)
            patterns.append("has-identity-services-icon")
            break

    # Many BTP service icons (>= 8) — full-blown landscape
    if len(profile.icons) >= 8:
        patterns.append("dense-icon-landscape")
    elif len(profile.icons) <= 3:
        patterns.append("sparse-icon-overview")

    # Multiple-pill flow (>= 5 pills) → labeled-flow diagram
    if len(profile.pills) >= 5:
        patterns.append("labeled-flow-multi-pill")

    # Dashed edges signal optional/async flows
    if any(e.is_dashed for e in profile.edges):
        patterns.append("uses-dashed-edges")

    # Properly anchored edges — quality signal for the LLM to imitate
    if profile.edges:
        anchored_pct = sum(1 for e in profile.edges if e.has_anchors) / len(profile.edges)
        if anchored_pct >= 0.7:
            patterns.append("well-anchored-edges")
        elif anchored_pct < 0.3:
            patterns.append("naked-edges-style")

    # Mostly orthogonal — SAP convention
    if profile.edges:
        ortho_pct = sum(1 for e in profile.edges if e.is_orthogonal) / len(profile.edges)
        if ortho_pct >= 0.8:
            patterns.append("orthogonal-edges-dominant")

    # Subaccount nested inside SAP BTP zone (RA0029 + IAM templates pattern)
    for z in profile.zones:
        if z.label.lower() == "subaccount" and z.parent_id and z.parent_id != "1":
            patterns.append("subaccount-nested-in-btp")
            break

    # Multi-zone pattern — reference families that use 4+ top-level zones
    top_level_zones = [z for z in profile.zones if z.parent_id == "1" or z.parent_id is None]
    if len(top_level_zones) >= 4:
        patterns.append("multi-zone-layout-4plus")
    elif len(top_level_zones) == 3:
        patterns.append("tri-zone-layout")
    elif len(top_level_zones) == 2:
        patterns.append("dual-zone-layout")

    return sorted(set(patterns))


# ---------- Description synthesizer ------------------------------------------

def _synthesize_description(profile: TemplateProfile) -> str:
    """One-paragraph plain-English summary of the template's design recipe."""
    parts = []
    parts.append(profile.title or profile.name)
    if profile.canvas_w and profile.canvas_h:
        parts.append(f"on a {profile.canvas_w}×{profile.canvas_h} canvas")
    top_zones = [z for z in profile.zones if z.parent_id in (None, "1")]
    zone_summary = ", ".join(
        f"{z.label or '(unnamed)'} [{z.color_role}]"
        for z in top_zones[:6]
    )
    if zone_summary:
        parts.append(f"with top-level zones: {zone_summary}")
    if profile.icons:
        size_summary = ", ".join(f"{n}× {s}" for s, n in sorted(profile.icon_sizes.items(), key=lambda kv: -kv[1])[:3])
        parts.append(f"and {len(profile.icons)} icons ({size_summary})")
    if profile.pills:
        vocab_summary = ", ".join(f"{lbl!r}" for lbl in list(dict.fromkeys(profile.pill_vocab))[:6])
        parts.append(f"plus {len(profile.pills)} flow pills using verbs {vocab_summary}")
    if profile.detected_patterns:
        parts.append(f"Detected patterns: {', '.join(profile.detected_patterns[:5])}")
    return ". ".join(parts) + "."


# ---------- Main extraction --------------------------------------------------

def profile_one(path: Path) -> TemplateProfile:
    metadata = _sel.template_metadata(path)
    profile = TemplateProfile(
        file=str(path),
        name=path.name,
        family=str(metadata.get("family", "")),
        level=str(metadata.get("level", "")),
        primary=bool(metadata.get("primary", False)),
        title=str(metadata.get("title", "")),
        aliases=list(metadata.get("aliases", [])) if isinstance(metadata.get("aliases"), list) else [],
        tags=list(metadata.get("tags", [])) if isinstance(metadata.get("tags"), list) else [],
        domain=str(metadata.get("domain", "")),
    )

    text = path.read_text(encoding="utf-8", errors="ignore")
    palette_text = DATA_URI_RE.sub("", text)
    profile.color_distribution = dict(Counter(h.upper() for h in HEX_RE.findall(palette_text)).most_common(20))
    profile.fonts = sorted(set(re.findall(r"fontFamily=([^;\"]+)", palette_text)))

    try:
        root = ET.parse(path).getroot()
    except ET.ParseError:
        return profile

    graph = root.find(".//mxGraphModel")
    if graph is not None:
        profile.canvas_w = int(graph.get("pageWidth") or "0")
        profile.canvas_h = int(graph.get("pageHeight") or "0")
        bg = graph.get("background") or graph.get("pageBackgroundColor") or ""
        profile.background = bg.strip().lower()

    parent_by_elem = {id(child): parent for parent in root.iter() for child in list(parent)}

    # --- Pass 1: collect cell metadata
    icon_geometries: dict[str, tuple[int, int, int, int]] = {}
    cells = []
    cell_lookup: dict[str, ET.Element] = {}
    for c in root.iter("mxCell"):
        cid = c.get("id")
        if not cid:
            parent_uo = parent_by_elem.get(id(c))
            if parent_uo is not None and parent_uo.tag == "UserObject":
                cid = parent_uo.get("id")
        if not cid:
            continue
        cells.append((cid, c))
        cell_lookup[cid] = c

    # --- Pre-pass: count children per cell so we can distinguish zone (container)
    # from card (leaf). Both can use rounded-rect style with strokeWidth=1.5; the
    # only visual difference is whether other cells are parented inside.
    children_count: dict[str, int] = {}
    for _, c in cells:
        parent = c.get("parent")
        if parent:
            children_count[parent] = children_count.get(parent, 0) + 1

    # --- Pass 2: classify each cell
    pill_labels: list[str] = []
    font_size_counter: Counter[str] = Counter()
    for cid, c in cells:
        style = c.get("style") or ""
        sd = _parse_style(style)
        is_vertex = c.get("vertex") == "1"
        is_edge = c.get("edge") == "1"

        # Geometry
        geo = c.find("mxGeometry")
        if geo is None:
            x = y = w = h = 0
        else:
            try:
                x = int(float(geo.get("x", "0")))
                y = int(float(geo.get("y", "0")))
                w = int(float(geo.get("width", "0")))
                h = int(float(geo.get("height", "0")))
            except ValueError:
                x = y = w = h = 0

        raw_value = c.get("value") or ""
        if not raw_value:
            parent_uo = parent_by_elem.get(id(c))
            if parent_uo is not None and parent_uo.tag == "UserObject":
                raw_value = parent_uo.get("value") or parent_uo.get("label") or ""
        label = _strip_label(raw_value)

        # Font sizes from inline HTML — heuristic
        for fs in re.findall(r"font-size\s*:\s*(\d+)", raw_value):
            font_size_counter[fs] += 1
        if sd.get("fontSize"):
            font_size_counter[sd["fontSize"]] += 1

        if is_edge:
            stroke = sd.get("strokeColor", "").upper()
            has_anchors = any(k in sd for k in ("entryX", "exitX", "entryY", "exitY"))
            is_ortho = sd.get("edgeStyle") == "orthogonalEdgeStyle"
            is_dashed = sd.get("dashed") == "1"
            profile.edges.append(EdgeInfo(
                cell_id=cid,
                source=c.get("source", ""),
                target=c.get("target", ""),
                stroke_color=stroke,
                has_anchors=has_anchors,
                is_orthogonal=is_ortho,
                is_dashed=is_dashed,
            ))
            continue

        if not is_vertex or w <= 0 or h <= 0:
            continue

        # Icon? — image with SVG or PNG, or mxgraph.sap.icon stencil
        is_icon = False
        image = sd.get("image", "")
        if sd.get("shape") == "image" and image.startswith(("data:image/svg", "data:image/png")):
            is_icon = True
        elif "mxgraph.sap.icon" in style:
            is_icon = True

        if is_icon:
            profile.icons.append(IconInfo(
                cell_id=cid,
                library_name=_icon_library_name(style),
                label=label[:60],
                w=w, h=h,
                parent_id=c.get("parent"),
            ))
            icon_geometries[cid] = (x, y, w, h)
            continue

        # Pill? — arcSize=50, small
        try:
            arc = int(float(sd.get("arcSize", "0")))
        except ValueError:
            arc = 0
        if arc >= 40 and w <= 220 and h <= 60:
            pill_labels.append(label.lower())
            profile.pills.append(PillInfo(
                cell_id=cid,
                label=label,
                fill=sd.get("fillColor", ""),
                stroke=sd.get("strokeColor", ""),
            ))
            continue

        # Zone? — rounded container with strokeWidth=1.5. SAP uses the same
        # rounded-rect style for zones and cards. We distinguish by either:
        #   (a) the cell has children parented inside it — definitively a zone
        #   (b) the cell is large enough to plausibly hold content
        #       (min dim >= 100 AND max dim >= 200 — cards are smaller)
        n_children = children_count.get(cid, 0)
        is_rounded_rect = (
            12 <= arc <= 30
            and sd.get("strokeWidth", "").rstrip(";") == "1.5"
        )
        is_zone = is_rounded_rect and (
            n_children >= 1
            or (min(w, h) >= 100 and max(w, h) >= 200)
        )
        if is_zone:
            stroke = sd.get("strokeColor", "")
            fill = sd.get("fillColor", "")
            profile.zones.append(ZoneInfo(
                cell_id=cid,
                label=label[:80],
                fill=fill,
                stroke=stroke,
                x=x, y=y, w=w, h=h,
                parent_id=c.get("parent"),
                color_role=_color_role(stroke),
            ))
            continue

        # Otherwise classify as a card if it has a fill and a label
        if sd.get("fillColor", "").lower() not in ("", "none"):
            # Determine which zone (if any) this card sits inside
            parent_zone_id: str | None = None
            for z in profile.zones:
                if z.cell_id == c.get("parent"):
                    parent_zone_id = z.cell_id
                    break
            profile.cards.append(CardInfo(
                cell_id=cid,
                label=label[:80],
                fill=sd.get("fillColor", ""),
                stroke=sd.get("strokeColor", ""),
                x=x, y=y, w=w, h=h,
                parent_zone=parent_zone_id,
            ))

    profile.icon_sizes = dict(Counter(f"{i.w}x{i.h}" for i in profile.icons).most_common(10))
    profile.pill_vocab = list(dict.fromkeys(pill_labels))
    profile.font_sizes = dict(font_size_counter.most_common(8))

    # Edge color distribution
    profile.edge_color_distribution = dict(
        Counter(e.stroke_color for e in profile.edges if e.stroke_color).most_common(8)
    )

    profile.edge_quality = {
        "total": len(profile.edges),
        "with_anchors": sum(1 for e in profile.edges if e.has_anchors),
        "orthogonal": sum(1 for e in profile.edges if e.is_orthogonal),
        "dashed": sum(1 for e in profile.edges if e.is_dashed),
    }

    profile.structure_summary = {
        "top_level_zones": sum(1 for z in profile.zones if z.parent_id in (None, "1")),
        "nested_zones": sum(1 for z in profile.zones if z.parent_id not in (None, "1")),
        "cards": len(profile.cards),
        "icons": len(profile.icons),
        "pills": len(profile.pills),
        "edges": len(profile.edges),
    }

    profile.detected_patterns = _detect_patterns(profile)
    profile.description = _synthesize_description(profile)

    return profile


def build_registry(refs_dir: Path, out_path: Path) -> int:
    refs = sorted(refs_dir.rglob("*.drawio"))
    profiles = {}
    for p in refs:
        try:
            profiles[p.name] = profile_one(p).to_dict()
        except Exception as e:
            print(f"warning: failed to profile {p.name}: {e}", file=sys.stderr)
            continue
    payload = {
        "version": 1,
        "purpose": "Pre-computed deep design profiles for every bundled SAP reference template. Consulted by iterate.py and find_pattern.py so the LLM can study the design recipe of its chosen scaffold.",
        "templates": profiles,
    }
    out_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return len(profiles)


def render_human(profile: TemplateProfile) -> str:
    lines: list[str] = []
    lines.append(f"=== {profile.name} ===")
    lines.append(f"Title    : {profile.title or '(no metadata title)'}")
    lines.append(f"Family   : {profile.family} | Level: {profile.level} | Domain: {profile.domain} | Primary: {profile.primary}")
    lines.append(f"Canvas   : {profile.canvas_w}×{profile.canvas_h}  bg={profile.background or '(white/none)'}")
    lines.append(f"Structure: {profile.structure_summary}")
    if profile.zones:
        lines.append("Zones    :")
        for z in profile.zones:
            depth = "  " if z.parent_id in (None, "1") else "    └ "
            lines.append(f"  {depth}{z.label or '(unnamed)':40s}  {z.color_role:30s} @ ({z.x},{z.y}) {z.w}×{z.h}")
    if profile.icons:
        lines.append(f"Icons    : {len(profile.icons)} total — sizes: {profile.icon_sizes}")
    if profile.pills:
        vocab_preview = ", ".join(f"{lbl!r}" for lbl in profile.pill_vocab[:8])
        lines.append(f"Pills    : {len(profile.pills)} — vocab: {vocab_preview}")
    if profile.edges:
        eq = profile.edge_quality
        lines.append(f"Edges    : {eq['total']} total — {eq['with_anchors']} anchored, {eq['orthogonal']} orthogonal, {eq['dashed']} dashed")
        if profile.edge_color_distribution:
            lines.append(f"           colors: {profile.edge_color_distribution}")
    if profile.detected_patterns:
        lines.append("Patterns :")
        for pat in profile.detected_patterns:
            lines.append(f"  • {pat}")
    lines.append(f"Recipe   : {profile.description}")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("file", nargs="?", type=Path, help="single .drawio to profile")
    ap.add_argument("--build-registry", action="store_true",
                    help="scan all bundled SAP refs and write template-profiles.json")
    ap.add_argument("--refs-dir", type=Path, default=None,
                    help="reference dir (default: bundled assets)")
    ap.add_argument("--out", type=Path, default=None,
                    help="output path for --build-registry (default: assets/reference-examples/template-profiles.json)")
    ap.add_argument("--json", action="store_true", help="emit JSON for one file")
    args = ap.parse_args()

    if args.build_registry:
        refs_dir = args.refs_dir or (THIS_DIR.parent / "assets" / "reference-examples")
        out_path = args.out or (refs_dir / "template-profiles.json")
        n = build_registry(refs_dir, out_path)
        print(f"profiled {n} templates → {out_path}")
        return 0

    if not args.file:
        print("either provide a .drawio path or pass --build-registry", file=sys.stderr)
        return 2

    profile = profile_one(args.file)
    if args.json:
        print(json.dumps(profile.to_dict(), indent=2))
    else:
        print(render_human(profile))
    return 0


if __name__ == "__main__":
    sys.exit(main())
