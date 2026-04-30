#!/usr/bin/env python3
"""Validate a SAP Architecture Center-style .drawio file.

Catches the bugs that make a diagram look unprofessional:

  Structural
    * malformed XML / missing mxGeometry / duplicate ids / comments
    * mxCell ids, including draw.io UserObject wrapper ids
  Alignment
    * x/y/width/height not integer multiples of 10 (grid-snap)
    * edge source+target don't share a center axis (bent arrows)
    * container children extending outside container bounds
    * overlapping siblings (unintended stacking)
  Text
    * label text wider than the shape (overflow / clipping)
    * edge label missing `labelBackgroundColor` (disappears in colored zone)
  Style
    * colors not in the SAP Horizon palette (warnings)
    * missing `absoluteArcSize=1` when `arcSize` is set (percent-rendering bug)
    * fontFamily not Helvetica
    * strokeWidth outside {1, 1.5, 3, 4}

Exit code:
  0 — clean (or only warnings)
  1 — errors
  2 — usage

Flags:
  --strict         warnings become errors
  --json           JSON report to stdout instead of human text

Run: python3 validate.py <file.drawio>
"""
from __future__ import annotations

import argparse
import html
import json
import re
import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path

# ---------- SAP Horizon palette ----------------------------------------------
# Source of truth, in priority order:
#   1. SAP/btp-solution-diagrams/guideline/docs/btp_guideline/foundation.md
#      and diagr_comp/areas.md (primary, semantic, accent)
#   2. Hex values observed in SAP/btp-solution-diagrams/assets/
#      editable-diagram-examples/*.drawio (real-world variations)
#   3. SAP/architecture-center/docs/ref-arch/RA*/drawio/*.drawio
SAP_PALETTE = {
    # --- foundation.md primary -------------------------------------------------
    "#0070F2", "#EBF8FF",          # SAP / BTP area: border, fill
    "#475E75", "#F5F6F7",          # Non-SAP area: border, fill
    "#1D2D3E",                     # Title text
    "#556B82",                     # Body text
    # --- foundation.md semantic ------------------------------------------------
    "#188918", "#F5FAE5",          # Positive (authentication flows)
    "#C35500", "#FFF8D6",          # Critical
    "#D20A0A", "#FFEAF4",          # Negative
    # --- foundation.md accent (sparingly) -------------------------------------
    "#07838F", "#DAFDF5",          # Teal
    "#5D36FF", "#F1ECFF",          # Indigo (authorization flows)
    "#CC00DC", "#FFF0FA",          # Pink (trust flows)
    # --- preset (in drawio-config-all-in-one.json) ----------------------------
    "#793802",                     # Brown — present in preset, no documented role
    # --- darker text / accent variants used in real SAP diagrams --------------
    "#002A86", "#00185A", "#0057D2", "#2395FF",  # SAP blue variants observed in Architecture Center
    "#266F3A",                     # darker positive green
    "#470BED",                     # darker indigo (preset variant of #5D36FF)
    "#7F00FF",                     # alt accent purple
    # --- observed grey / neutral variations (real SAP files) ------------------
    "#1A2733",                     # near-black navy used by some diagrams
    "#354A5F",                     # mid grey
    "#475E74", "#475F75",          # off-by-one variants of #475E75
    "#5B738B",                     # lighter grey
    "#595959",
    "#D5DADD", "#EAECEE", "#EDEDED", "#EDEFF0", "#EAF8FF", "#EDF8FF", "#ECF8FF",
    "#D1EFFF", "#CCDDFF",
    "#FCFCFC",
    # --- basics ----------------------------------------------------------------
    "#FFFFFF", "#FFF", "#000000", "#000",
}

COMMENT_RE = re.compile(r"<!--.*?-->", re.S)
HEX_RE = re.compile(r"#[0-9A-Fa-f]{6}\b")
# data URIs embed their own palette we should NOT flag
DATA_URI_RE = re.compile(r"data:image/[^&\";]+")

GRID = 10
ALLOWED_STROKE = {"1", "1.5", "2", "3", "4"}

# Canonical SAP flow-pill vocabulary, extracted from the published reference
# corpus. Pills with labels outside this set tend to indicate hand-crafted
# diagrams rather than SAP-style flow narration. We don't enforce strictly —
# many cases legitimately add custom verbs — but emit a warning so reviewers
# can ratify the deviation.
CANONICAL_PILL_LABELS = {
    # identity / trust / auth
    "trust", "authenticate", "authentication", "authorization",
    "identity", "identity lifecycle", "customer-managed identity lifecycle",
    "user", "usergroup", "group", "role", "role collection", "role collections",
    "policy", "scim", "saml2/oidc", "oidc", "saml", "openid",
    # transport
    "https", "https/active", "https/standby", "rest", "rest/spi",
    "rest/token", "rest / odata", "odata/rest", "odata/rest/soap",
    # data flows
    "destination", "source", "target", "harmonized api",
    "data federation", "data sync", "task data",
    # agentic ai vocab seen in RA0029 family
    "a2a", "mcp", "ord",
    # business
    "business data cloud", "business role", "cdm",
    # other observed
    "role replica",
    # generic but acceptable
    "data", "metadata",
}

# Pill labels Codex observed in failed generations (PROMPT, ROUTE, CONTEXT,
# DELEGATE, etc.) — explicit watch-list to surface the most common drift.
NOVELTY_PILL_LABELS = {
    "prompt", "route", "context", "delegate", "answer", "ask", "respond",
    "query", "fetch", "invoke", "call", "execute", "run", "process",
    "send", "receive", "publish", "subscribe", "transform",
}

# Light/neutral page backgrounds we accept. Anything else (dark, branded,
# strongly tinted) is suspect because no SAP reference uses one.
ALLOWED_PAGE_BACKGROUNDS = {None, "", "none", "default", "#ffffff", "#fff", "#FFFFFF", "#FFF"}


# ---------- Report model -----------------------------------------------------


@dataclass
class Issue:
    kind: str  # "error" | "warning"
    category: str  # "xml", "align", "text", "style"
    msg: str
    cell: str | None = None


@dataclass
class Report:
    path: str
    issues: list[Issue] = field(default_factory=list)

    def add(self, kind: str, category: str, msg: str, cell: str | None = None) -> None:
        self.issues.append(Issue(kind, category, msg, cell))

    @property
    def errors(self) -> list[Issue]:
        return [i for i in self.issues if i.kind == "error"]

    @property
    def warnings(self) -> list[Issue]:
        return [i for i in self.issues if i.kind == "warning"]

    def to_json(self) -> dict:
        return {
            "path": self.path,
            "ok": not self.errors,
            "errors": [{"category": i.category, "msg": i.msg, "cell": i.cell} for i in self.errors],
            "warnings": [{"category": i.category, "msg": i.msg, "cell": i.cell} for i in self.warnings],
        }


# ---------- Geometry helpers -------------------------------------------------


def geom(cell: ET.Element) -> tuple[float, float, float, float] | None:
    g = cell.find("mxGeometry")
    if g is None:
        return None
    try:
        x = float(g.get("x", "0"))
        y = float(g.get("y", "0"))
        w = float(g.get("width", "0"))
        h = float(g.get("height", "0"))
        return x, y, w, h
    except ValueError:
        return None


def parse_style(style: str | None) -> dict[str, str]:
    if not style:
        return {}
    out: dict[str, str] = {}
    for part in style.split(";"):
        part = part.strip()
        if not part:
            continue
        if "=" in part:
            k, v = part.split("=", 1)
            out[k.strip()] = v.strip()
        else:
            out[part] = "1"
    return out


def approx_text_width(text: str, font_size: float, bold: bool = False) -> float:
    """Crude width estimate in px. Good enough to catch egregious overflow."""
    if not text:
        return 0.0
    # avg char width ≈ 0.55 × font_size for Helvetica regular, 0.60 bold
    coef = 0.60 if bold else 0.55
    return len(text) * font_size * coef


def visible_label_lines(label: str) -> list[str]:
    """Reduce an HTML-ish draw.io label to visible text lines."""
    label = html.unescape(label or "")
    label = re.sub(r"</(?:div|p|li)>", "\n", label, flags=re.I)
    label = re.sub(r"<br\s*/?>", "\n", label, flags=re.I)
    no_tags = re.sub(r"<[^>]+>", "", label)
    lines = [re.sub(r"\s+", " ", line).strip() for line in no_tags.splitlines()]
    return [line for line in lines if line]


def strip_html(label: str) -> str:
    """Reduce HTML label to its visible text (rough)."""
    return " ".join(visible_label_lines(label))


def html_font_size(label: str, fallback: float) -> float:
    """Best-effort font-size extraction from draw.io rich text labels."""
    sizes: list[float] = []
    for value in re.findall(r"font-size\s*:\s*([0-9.]+)\s*px", label or "", flags=re.I):
        try:
            sizes.append(float(value))
        except ValueError:
            pass
    for value in re.findall(r"<font[^>]*\bsize=[\"']?([0-9]+)", label or "", flags=re.I):
        # draw.io/browser HTML font size 1 renders small; this is only a fit heuristic.
        sizes.append({"1": 10.0, "2": 11.0, "3": 12.0, "4": 14.0, "5": 18.0, "6": 24.0, "7": 32.0}.get(value, fallback))
    return min(sizes) if sizes else fallback


def bbox_overlap(a: tuple[float, float, float, float], b: tuple[float, float, float, float]) -> float:
    """Return overlap area in px². 0 if no overlap."""
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    dx = max(0.0, min(ax + aw, bx + bw) - max(ax, bx))
    dy = max(0.0, min(ay + ah, by + bh) - max(ay, by))
    return dx * dy


# ---------- Validators -------------------------------------------------------


def validate(path: Path) -> Report:
    report = Report(path=str(path))
    text = path.read_text(encoding="utf-8")

    if COMMENT_RE.search(text):
        report.add("error", "xml", "XML comments (<!-- -->) forbidden — strip them")

    try:
        root = ET.fromstring(text)
    except ET.ParseError as exc:
        report.add("error", "xml", f"XML parse error: {exc}")
        return report

    # ---- collect cells & basic structural checks ---------------------------
    parent_by_elem = {id(child): parent for parent in root.iter() for child in list(parent)}

    def effective_cell_id(cell: ET.Element) -> str | None:
        cid = cell.get("id")
        if cid:
            return cid
        parent = parent_by_elem.get(id(cell))
        if parent is not None and parent.tag == "UserObject":
            return parent.get("id")
        return None

    graphs = root.findall(".//mxGraphModel") or [root]

    # Page background colour — SAP diagrams are always on a white/transparent canvas.
    for graph_index, graph in enumerate(graphs):
        bg = graph.get("background") or graph.get("pageBackgroundColor")
        if bg and bg.strip().lower() not in {b.lower() for b in ALLOWED_PAGE_BACKGROUNDS if b}:
            suffix = "" if len(graphs) == 1 else f" (page {graph_index + 1})"
            report.add(
                "error",
                "style",
                f"page background {bg!r}{suffix} — SAP diagrams use a white/transparent canvas; "
                "remove the dark/branded background.",
            )

    def scoped_id(graph_index: int, cell_id: str) -> str:
        return cell_id if len(graphs) == 1 else f"{graph_index}:{cell_id}"

    cells: dict[str, ET.Element] = {}
    cell_scopes: dict[str, int] = {}
    duplicate_ids: set[tuple[int, str]] = set()
    for graph_index, graph in enumerate(graphs):
        seen_in_graph: set[str] = set()
        for cell in graph.iter("mxCell"):
            cid = effective_cell_id(cell)
            if cid is None:
                report.add("error", "xml", "mxCell without id attribute")
                continue
            if cid in seen_in_graph:
                duplicate_ids.add((graph_index, cid))
            seen_in_graph.add(cid)

            key = scoped_id(graph_index, cid)
            cells[key] = cell
            cell_scopes[key] = graph_index

            is_vertex = cell.get("vertex") == "1"
            is_edge = cell.get("edge") == "1"
            if (is_vertex or is_edge) and cell.find("mxGeometry") is None:
                report.add("error", "xml", "vertex/edge missing <mxGeometry>", cell=key)

    for graph_index, cid in duplicate_ids:
        suffix = "" if len(graphs) == 1 else f" in diagram page {graph_index + 1}"
        report.add("error", "xml", f"duplicate id {cid!r}{suffix}")

    # ---- style / palette ---------------------------------------------------
    palette_text = DATA_URI_RE.sub("", text)
    foreign = {m.upper() for m in HEX_RE.findall(palette_text)} - {c.upper() for c in SAP_PALETTE}
    for color in sorted(foreign):
        report.add("warning", "style", f"off-palette color {color}")

    # ---- per-cell checks ---------------------------------------------------
    for cid, cell in cells.items():
        style = parse_style(cell.get("style"))

        # Grid snap
        g = geom(cell)
        if g:
            x, y, w, h = g
            for name, val in (("x", x), ("y", y), ("width", w), ("height", h)):
                if abs(val - round(val)) > 0.01 or int(round(val)) % GRID != 0:
                    report.add(
                        "warning",
                        "align",
                        f"{name}={val!r} not on {GRID}-px grid",
                        cell=cid,
                    )

        # absoluteArcSize when arcSize present
        if "arcSize" in style and style.get("absoluteArcSize") != "1":
            report.add(
                "warning",
                "style",
                "arcSize without absoluteArcSize=1 renders as percentage",
                cell=cid,
            )

        # Font family
        ff = style.get("fontFamily")
        if ff and ff.lower() != "helvetica":
            report.add("warning", "style", f"fontFamily={ff!r} (expected Helvetica)", cell=cid)

        # Image source hygiene
        image = style.get("image")
        if image and image.startswith(("http://", "https://")):
            report.add("warning", "style", "external image URL — prefer bundled SAP inline assets", cell=cid)
        elif image and not (image.startswith("data:image/") or image == "img/lib/sap/SAP_Logo.svg"):
            report.add("warning", "style", f"non-bundled image source {image!r}", cell=cid)

        # Stroke width
        sw = style.get("strokeWidth")
        if sw and sw not in ALLOWED_STROKE:
            report.add("warning", "style", f"strokeWidth={sw!r} (expected one of {sorted(ALLOWED_STROKE)})", cell=cid)

        # Edge-label background
        if cell.get("edge") == "1":
            val = cell.get("value") or ""
            if val.strip() and not style.get("labelBackgroundColor"):
                report.add(
                    "warning",
                    "text",
                    "edge label without labelBackgroundColor (will bleed into zone fill)",
                    cell=cid,
                )
            if "endArrow" not in style and "startArrow" not in style:
                report.add("warning", "style", "edge without endArrow style", cell=cid)

        # Text overflow (vertex only, has a label, has geometry)
        if cell.get("vertex") == "1" and g:
            raw_label = cell.get("value") or ""
            label = strip_html(raw_label)
            if label and style.get("autosize") != "1" and style.get("shape") != "image" and "image" not in style:
                font_size = html_font_size(raw_label, float(style.get("fontSize", "12")))
                bold = style.get("fontStyle", "0") in {"1", "3", "5", "7"}
                spacing = float(style.get("spacingLeft", "0")) + float(style.get("spacingRight", "0"))
                wrap = style.get("whiteSpace") == "wrap" and style.get("html") == "1"
                effective_w = g[2] - spacing - 6  # 6 px slop
                if wrap:
                    # With wrapping, only the single longest token needs to fit
                    longest = max(label.split(), key=len, default="")
                    need = approx_text_width(longest, font_size, bold)
                    if effective_w > 0 and need > effective_w + 6:
                        report.add(
                            "warning",
                            "text",
                            f"longest word '{longest}' ~{int(need)}px > shape width {int(g[2])}px — clip",
                            cell=cid,
                        )
                else:
                    longest_line = max(visible_label_lines(raw_label) or [label], key=len)
                    need = approx_text_width(longest_line, font_size, bold)
                    if effective_w > 0 and need > effective_w + 6:
                        report.add(
                            "warning",
                            "text",
                            f"label ~{int(need)}px wider than shape ({int(g[2])}px) — text will clip",
                            cell=cid,
                        )

    # ---- pill / flow-narration vocabulary check ---------------------------
    # A pill is roughly arcSize >= 40 with a label. SAP's published corpus uses
    # a small canonical vocabulary (TRUST, Authenticate, A2A, MCP, ORD, HTTPS,
    # OData/REST, …). Custom verbs like PROMPT/ROUTE/CONTEXT/DELEGATE indicate
    # an LLM hand-crafted the diagram instead of starting from a template.
    # Track the labels we saw, then warn for each one outside the canon.
    seen_pill_labels: list[tuple[str, str]] = []  # (label, cid)
    novelty_pills: list[tuple[str, str]] = []
    for cid, cell in cells.items():
        if cell.get("vertex") != "1":
            continue
        style = parse_style(cell.get("style"))
        try:
            arc = int(float(style.get("arcSize", "0")))
        except ValueError:
            arc = 0
        if arc < 40:
            continue
        # Pill must be small (single line, < 200 px wide). Larger rounded
        # shapes can be cards or banners, which use a separate label vocab.
        g = geom(cell)
        if not g or g[2] > 220 or g[3] > 60:
            continue
        raw = cell.get("value") or ""
        # UserObject wrapping: a parent UserObject may carry the visible label
        if not raw:
            parent = parent_by_elem.get(id(cell))
            if parent is not None and parent.tag == "UserObject":
                raw = parent.get("value") or parent.get("label") or ""
        label_text = strip_html(raw).strip()
        if not label_text:
            continue
        seen_pill_labels.append((label_text, cid))
        normalized = label_text.lower()
        if normalized in CANONICAL_PILL_LABELS:
            continue
        # Single-token novelty pill — the most common LLM drift mode.
        first_token = normalized.split()[0] if normalized else ""
        if first_token in NOVELTY_PILL_LABELS:
            novelty_pills.append((label_text, cid))
            report.add(
                "warning",
                "text",
                f"flow pill {label_text!r} is not in the canonical SAP vocabulary "
                "(TRUST/Authenticate/A2A/MCP/ORD/HTTPS/OData/REST/…). "
                "Replace with a SAP-style verb or remove the pill.",
                cell=cid,
            )

    # ---- sibling overlap checks (vertices sharing a parent) ---------------
    def is_transparent_or_chrome(cell: ET.Element) -> bool:
        """Cells that float on top of others by design and shouldn't be flagged."""
        s = parse_style(cell.get("style"))
        if s.get("fillColor") in (None, "none"):
            return True
        if s.get("shape") in ("ellipse", "image"):
            return True
        # pill (arcSize >= 40 roughly)
        try:
            if int(s.get("arcSize", "0")) >= 40:
                return True
        except ValueError:
            pass
        # text-only cells
        if s.get("text") == "1" or s.get("strokeColor") == "none":
            return True
        return False

    by_parent: dict[str, list[tuple[str, tuple[float, float, float, float], ET.Element]]] = {}
    for cid, cell in cells.items():
        if cell.get("vertex") != "1":
            continue
        parent = scoped_id(cell_scopes[cid], cell.get("parent") or "")
        g = geom(cell)
        if not g or g[2] <= 0 or g[3] <= 0:
            continue
        by_parent.setdefault(parent, []).append((cid, g, cell))

    for parent, members in by_parent.items():
        for i in range(len(members)):
            for j in range(i + 1, len(members)):
                ida, ga, ca = members[i]
                idb, gb, cb = members[j]
                ov = bbox_overlap(ga, gb)
                if ov <= 100:  # ignore slivers
                    continue
                ax, ay, aw, ah = ga
                bx, by_, bw, bh = gb
                contains = (ax <= bx and ay <= by_ and ax + aw >= bx + bw and ay + ah >= by_ + bh) or (
                    bx <= ax and by_ <= ay and bx + bw >= ax + aw and by_ + bh >= ay + ah
                )
                if contains:
                    continue
                # Pills / icons / text / transparent cells are allowed to float over frames
                if is_transparent_or_chrome(ca) or is_transparent_or_chrome(cb):
                    continue
                report.add(
                    "warning",
                    "align",
                    f"cells {ida} and {idb} overlap by {int(ov)}px² (same parent {parent})",
                )

    # ---- bent-edge detection ----------------------------------------------
    for cid, cell in cells.items():
        if cell.get("edge") != "1":
            continue
        src_id = cell.get("source")
        tgt_id = cell.get("target")
        if not src_id or not tgt_id:
            continue
        style = parse_style(cell.get("style"))
        if style.get("edgeStyle") != "orthogonalEdgeStyle":
            continue  # non-orthogonal edges may legitimately curve
        # Skip edges with explicit entry/exit anchors — author has chosen the docking
        if any(k in style for k in ("entryX", "exitX", "entryY", "exitY")):
            continue
        scope = cell_scopes[cid]
        src = cells.get(scoped_id(scope, src_id))
        tgt = cells.get(scoped_id(scope, tgt_id))
        if src is None or tgt is None:
            continue
        gs = geom(src)
        gt = geom(tgt)
        if not gs or not gt:
            continue
        cx_s = gs[0] + gs[2] / 2
        cy_s = gs[1] + gs[3] / 2
        cx_t = gt[0] + gt[2] / 2
        cy_t = gt[1] + gt[3] / 2
        aligned_v = abs(cx_s - cx_t) <= 1.0  # centers on same vertical
        aligned_h = abs(cy_s - cy_t) <= 1.0  # centers on same horizontal
        if not (aligned_v or aligned_h):
            # Is there overlap on an axis? If boxes overlap on X the edge can still drop straight
            overlap_x = min(gs[0] + gs[2], gt[0] + gt[2]) - max(gs[0], gt[0])
            overlap_y = min(gs[1] + gs[3], gt[1] + gt[3]) - max(gs[1], gt[1])
            if overlap_x < 10 and overlap_y < 10:
                report.add(
                    "warning",
                    "align",
                    f"edge {cid}: source/target centers differ on both axes "
                    f"(Δx={cx_s - cx_t:.0f}, Δy={cy_s - cy_t:.0f}) — arrow will bend. "
                    "Either snap centers or add entryX/exitX anchors.",
                    cell=cid,
                )

    # ---- duplicate SAP logos check ----------------------------------------
    # SAP guideline: "It is not recommended to use too many SAP logos in the
    # same diagram." (product_names.md). One inline SAP_Logo.svg per zone-band
    # is acceptable; more than ~4 in a single page is suspicious.
    sap_logo_count = 0
    for cid, cell in cells.items():
        style = parse_style(cell.get("style"))
        image = style.get("image")
        if image and "sap_logo" in image.lower():
            sap_logo_count += 1
    if sap_logo_count > 6:
        report.add(
            "warning",
            "style",
            f"{sap_logo_count} SAP logos detected — SAP recommends limiting logo "
            "repetition. Use text-only product labels instead beyond zone branding.",
        )

    return report


# ---------- Output ----------------------------------------------------------


def print_text(report: Report) -> None:
    path = report.path
    if not report.issues:
        print(f"{path}: OK")
        return
    for i in report.warnings:
        loc = f" [{i.cell}]" if i.cell else ""
        print(f"{path}: warning ({i.category}){loc}: {i.msg}")
    for i in report.errors:
        loc = f" [{i.cell}]" if i.cell else ""
        print(f"{path}: error ({i.category}){loc}: {i.msg}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("files", nargs="+")
    ap.add_argument("--strict", action="store_true", help="warnings fail the run")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    rc = 0
    reports = []
    for f in args.files:
        p = Path(f)
        if not p.exists():
            print(f"{p}: not found", file=sys.stderr)
            rc = 1
            continue
        r = validate(p)
        reports.append(r)
        if r.errors or (args.strict and r.warnings):
            rc = 1

    if args.json:
        print(json.dumps([r.to_json() for r in reports], indent=2))
    else:
        for r in reports:
            print_text(r)

    return rc


if __name__ == "__main__":
    sys.exit(main())
