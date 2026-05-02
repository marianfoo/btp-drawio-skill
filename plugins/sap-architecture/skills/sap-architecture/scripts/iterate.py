#!/usr/bin/env python3
"""LLM-friendly iteration helper for the nudge workflow.

The point of this script is to give a multimodal LLM (Claude Sonnet 4.x in
Cursor, GPT-5, etc.) the three things it needs after every edit to plan its
next move:

  1. A fresh PNG of the candidate it just edited.
  2. A PNG of the SAP target template it should converge toward.
  3. A compact, prioritized text breakdown — score, lowest dimensions,
     and concrete next-step suggestions tied to specific cells.

Usage:

  iterate.py <candidate.drawio>
  iterate.py <candidate.drawio> --target <reference.drawio>

When --target is omitted we score against the full bundled corpus and
pick the closest match (this is what the LLM gets after a fresh scaffold,
since the target template is well known then).

The script writes its artifacts under .cache/sap-architecture-iter/<stem>/
so consecutive iterations overwrite cleanly without polluting the project.

Output is structured for an LLM reader:

  ─── SAP DIAGRAM ITERATION ───
  candidate    : docs/architecture/foo.drawio
  target       : .../ac_RA0029_AgenticAI_root.drawio  (auto-picked)
  current      : 78.4 / 100   ← changed +3.2 since last iterate
  pass gate    : 90.0

  📷 Read these images with your vision tool to plan the next edit:
     candidate :  .cache/.../foo.candidate.png
     reference :  .cache/.../ac_RA0029_AgenticAI_root.reference.png
     diff      :  .cache/.../foo.diff.html  (browser-renderable side-by-side)

  ⚠ Lowest-scoring dimensions (fix worst first):
     zones       45%  cand=4 ref=8     ← biggest gap
     icons       55%  cand=5 ref=11
     pill_vocab  60%  novelty="PROMPT" — replace with "TRUST" / "Authenticate"
     edge_pal    33%  missing #CC00DC pink, #5D36FF indigo on edges

  ✏ Next concrete edit (do ONE, then re-run iterate.py):
     1. Add 4 zone containers using the same arcSize=16, strokeWidth=1.5
        style. Look at the reference PNG for placement.
     2. Add 6 BTP service icons via:
        python3 .../scripts/extract_icon.py "<service>" --x ... --y ...
     3. Replace pill text "PROMPT" with "TRUST" (cells matching arcSize=50).

  ⏪ Last iteration: -2.3 (you regressed). Inspect what changed and
     consider rolling back the last edit if it wasn't intentional.

The HTML diff is the same artifact `render_compare.py` produces, but
with caching keyed off file mtime so iterate.py is fast to re-run.

Exit code:
  0 — score >= --min-score (passes the gate)
  1 — score below the gate (more iteration needed)
  2 — render or compare failed
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

THIS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(THIS_DIR))

import compare as _compare        # noqa: E402
import render as _render          # noqa: E402
import select_reference as _sel   # noqa: E402


CACHE_ROOT = Path(".cache") / "sap-architecture-iter"


def find_target(candidate: Path, refs_dir: Path) -> tuple[Path, float, str]:
    """Pick the closest SAP reference template for the candidate.

    Strategy: corpus fingerprint scoring is more reliable than text matching
    because the candidate's labels often diverge from its source template
    after edits. We score the candidate against every bundled reference, take
    the top by fingerprint, and (if the fingerprint match is decisive) use
    it. For ambiguous matches we cross-check with the textual selector.
    """
    refs = sorted(refs_dir.rglob("*.drawio"))
    cand_fp = _compare.fingerprint(candidate)

    fingerprint_scores: list[tuple[float, Path]] = []
    for p in refs:
        try:
            ref_fp = _compare.fingerprint(p)
            s = _compare.compare(ref_fp, cand_fp).score
        except Exception:
            continue
        fingerprint_scores.append((s, p))
    fingerprint_scores.sort(key=lambda x: -x[0])

    if fingerprint_scores and fingerprint_scores[0][0] >= 90:
        return fingerprint_scores[0][1], fingerprint_scores[0][0], "corpus fingerprint match (high confidence)"

    # Mid-confidence: cross-check fingerprint top-5 with textual selector top-3
    cand_text = candidate.read_text(encoding="utf-8", errors="ignore")
    head = cand_text[:2000]
    textual = sorted(
        (_sel.score(p, f"{candidate.stem} {head}") for p in refs),
        key=lambda c: (-c.score, c.path),
    )[:5]
    if textual:
        textual_top = {Path(c.path) for c in textual[:3]}
        for s, p in fingerprint_scores[:5]:
            if p in textual_top:
                return p, s, "fingerprint+textual agreement"

    if fingerprint_scores:
        return fingerprint_scores[0][1], fingerprint_scores[0][0], "best fingerprint match"
    if textual:
        return Path(textual[0].path), float(textual[0].score), "textual selector fallback"
    return refs[0], 0.0, "first available reference (no signal)"


def cache_dir_for(candidate: Path) -> Path:
    cache = CACHE_ROOT / candidate.stem
    cache.mkdir(parents=True, exist_ok=True)
    return cache


def render_if_stale(cli: str, src: Path, dst: Path, scale: float, border: int) -> bool:
    """Render src.drawio to dst.png only if dst is older than src."""
    if dst.exists() and dst.stat().st_mtime >= src.stat().st_mtime:
        return False
    rc = _render.render_one(cli, src, dst, "png", scale, border, transparent=False, quiet=True)
    if rc != 0:
        raise RuntimeError(f"render of {src} failed (rc={rc})")
    return True


def write_diff_html(
    out_dir: Path,
    candidate: Path,
    target: Path,
    cand_png: Path,
    ref_png: Path,
    score: float,
    breakdown: dict,
    diffs: list[str],
    suggestions: list[str],
) -> Path:
    """Reuse render_compare.py's HTML template (delegates so we keep one source of truth)."""
    # Easiest: just shell out to render_compare.py. It already writes review.html.
    # We pass --out-dir so it writes alongside our cached PNGs.
    rc = subprocess.run(
        [
            sys.executable,
            str(THIS_DIR / "render_compare.py"),
            str(target),
            str(candidate),
            "--out-dir",
            str(out_dir),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if rc.returncode != 0:
        # Non-fatal — we already have the PNGs and score; HTML is a bonus.
        return out_dir / "review.html"
    return out_dir / "review.html"


def collect_validator_warnings(candidate: Path) -> dict[str, list[str]]:
    """Run validate.py and group warnings by category for the LLM.

    We treat icon/edge align warnings as the highest-priority feedback for
    the LLM — they pinpoint exact cell IDs to fix and are the visible
    failures (oversized icons, icons-on-text, edges-through-cells).
    """
    out: dict[str, list[str]] = {"icon_oversized": [], "icon_overlap": [], "edge_through": [], "other": []}
    rc = subprocess.run(
        [sys.executable, str(THIS_DIR / "validate.py"), str(candidate), "--json"],
        capture_output=True, text=True, check=False,
    )
    if rc.returncode not in (0, 1):
        return out
    try:
        data = json.loads(rc.stdout)
    except json.JSONDecodeError:
        return out
    if not isinstance(data, list) or not data:
        return out
    report = data[0]
    for w in (report.get("warnings") or []):
        msg = w.get("msg", "")
        cell = w.get("cell", "")
        line = f"[{cell}] {msg}" if cell else msg
        if "oversized" in msg and "icon" in msg:
            out["icon_oversized"].append(line)
        elif "icon" in msg and "overlaps card" in msg:
            out["icon_overlap"].append(line)
        elif "edge" in msg and "passes through" in msg:
            out["edge_through"].append(line)
        else:
            out["other"].append(line)
    return out


def actionable_suggestions(breakdown: dict, ref_fp, cand_fp, raw_diffs: list[str], validator_groups: dict[str, list[str]] | None = None) -> list[str]:
    """Pull concrete, single-action suggestions from the score breakdown.

    Validator-detected layout failures (oversized icons, icon overlaps,
    edges through boxes) get the top of the list because they are
    visually obvious to the user even when the score is still high.
    """
    weighted_gaps: list[tuple[float, str]] = []

    # Validator-detected layout failures rank highest — they are the visible
    # bugs the user will spot immediately ("icon is huge", "arrow goes
    # through a box"), even when the structural fingerprint score is OK.
    if validator_groups:
        if validator_groups["icon_oversized"]:
            n = len(validator_groups["icon_oversized"])
            sample = validator_groups["icon_oversized"][0]
            weighted_gaps.append((
                1000.0,  # always first
                f"Resize {n} oversized icon(s) to 32×32 (most common in SAP corpus) "
                f"or 48×48 for focal anchors. Use --w 32 --h 32 with extract_icon.py, "
                f"or edit `<mxGeometry width=\"...\" height=\"...\">` directly. "
                f"Example: {sample}"
            ))
        if validator_groups["icon_overlap"]:
            n = len(validator_groups["icon_overlap"])
            sample = validator_groups["icon_overlap"][0]
            weighted_gaps.append((
                950.0,
                f"Move {n} icon(s) off the cards they overlap. Either tuck the icon "
                f"INSIDE its parent card (set parent attribute and small x/y inside the card), "
                f"or relocate it to an empty region of the canvas. Example: {sample}"
            ))
        if validator_groups["edge_through"]:
            n = len(validator_groups["edge_through"])
            sample = validator_groups["edge_through"][0]
            weighted_gaps.append((
                900.0,
                f"Reroute {n} edge(s) so they don't cross unrelated cards. Two fixes "
                f"per edge: (a) add `edgeStyle=orthogonalEdgeStyle;` to the edge style + "
                f"`exitX=0/0.5/1;exitY=0/0.5/1;entryX=...;entryY=...;exitDx=0;exitDy=0;` "
                f"to dock to a specific edge of the source/target; OR (b) reposition the "
                f"source/target cells so the straight line has no obstacle. "
                f"Example: {sample}"
            ))

    weights = {
        "page_bg": 1.5, "canvas": 1.0, "zones": 1.5, "zone_depth": 1.0,
        "icons": 1.5, "pill_vocab": 1.5, "edge_palette": 1.0, "palette": 1.5,
        "label_tokens": 2.0, "fonts": 1.0, "shapes": 1.0, "grid_snap": 1.0,
        "pills": 0.5, "vertices": 0.5, "edges": 1.0, "label_count": 0.5,
        "abs_arc": 0.5, "label_bg": 0.5, "strokes": 0.5, "external_images": 0.5,
    }

    if breakdown.get("page_bg", 1.0) < 1.0:
        weighted_gaps.append((
            weights.get("page_bg", 1) * (1 - breakdown["page_bg"]),
            f"Set canvas background to white. Remove "
            f"`pageBackgroundColor=\"{cand_fp.page_background or '?'}\"` from <mxGraphModel>."
        ))
    if breakdown.get("canvas", 1.0) < 1.0:
        weighted_gaps.append((
            weights.get("canvas", 1) * (1 - breakdown["canvas"]),
            f"Resize canvas to {ref_fp.canvas_w}×{ref_fp.canvas_h} (currently "
            f"{cand_fp.canvas_w}×{cand_fp.canvas_h}). draw.io: File → Page Setup → Custom."
        ))
    if breakdown.get("zones", 1.0) < 0.7:
        delta = abs(ref_fp.zones - cand_fp.zones)
        verb = "Add" if cand_fp.zones < ref_fp.zones else "Remove"
        weighted_gaps.append((
            weights.get("zones", 1) * (1 - breakdown["zones"]),
            f"{verb} {delta} zone container(s). Reference has {ref_fp.zones} zones; "
            f"you have {cand_fp.zones}. Use rounded rect with arcSize=16, strokeWidth=1.5, "
            "and a top-left bold inline label."
        ))
    if breakdown.get("zone_depth", 1.0) < 1.0:
        weighted_gaps.append((
            weights.get("zone_depth", 1) * (1 - breakdown["zone_depth"]),
            f"Zone nesting depth differs (cand={cand_fp.zone_depth}, ref={ref_fp.zone_depth}). "
            "Common bug: putting Joule INSIDE the BTP zone when SAP places them side-by-side."
        ))
    if breakdown.get("icons", 1.0) < 0.7:
        delta = abs(ref_fp.icons - cand_fp.icons)
        verb = "Add" if cand_fp.icons < ref_fp.icons else "Remove"
        weighted_gaps.append((
            weights.get("icons", 1) * (1 - breakdown["icons"]),
            f"{verb} {delta} BTP service icon(s). Use scripts/extract_icon.py "
            "\"<service-name>\" --x <X> --y <Y> --id <id> to get a ready mxCell."
        ))
    if breakdown.get("pill_vocab", 1.0) < 1.0 and cand_fp.novelty_pill_count:
        weighted_gaps.append((
            weights.get("pill_vocab", 1) * (1 - breakdown["pill_vocab"]),
            f"Replace {cand_fp.novelty_pill_count} novelty pill verb(s). Allowed: "
            "TRUST, Authenticate, Authorization, A2A, MCP, ORD, HTTPS, OData/REST, "
            "SAML2/OIDC, SCIM, Identity Lifecycle. Forbidden: PROMPT, ROUTE, CONTEXT, "
            "DELEGATE, INVOKE, FETCH, EXECUTE."
        ))
    if breakdown.get("edge_palette", 1.0) < 0.6:
        missing = sorted(set(ref_fp.edge_palette) - set(cand_fp.edge_palette))[:4]
        if missing:
            weighted_gaps.append((
                weights.get("edge_palette", 1) * (1 - breakdown["edge_palette"]),
                f"Add SAP-mandated edge stroke colors: {', '.join(missing)}. Mapping: "
                "trust=#CC00DC pink, auth=#188918 green, authorization=#5D36FF indigo, "
                "structural=#475E75 slate, MCP=#07838F teal."
            ))
    if breakdown.get("palette", 1.0) < 0.6:
        weighted_gaps.append((
            weights.get("palette", 1) * (1 - breakdown["palette"]),
            "Palette overlap is low — many of your fill/stroke hexes aren't in the SAP set. "
            "Replace custom colors with the Horizon palette listed in references/palette-and-typography.md."
        ))
    if breakdown.get("label_tokens", 1.0) < 0.5:
        weighted_gaps.append((
            weights.get("label_tokens", 1) * (1 - breakdown["label_tokens"]),
            "Label vocabulary drifted — most card/zone labels don't match the reference. "
            "Restore the SAP service names you removed, or rename your cards to use SAP product terminology."
        ))
    if breakdown.get("grid_snap", 1.0) < 0.9:
        weighted_gaps.append((
            weights.get("grid_snap", 1) * (1 - breakdown["grid_snap"]),
            "Geometry off the 10-px grid. Run `python3 scripts/autofix.py --write <file>` "
            "— this is mechanical and won't change content."
        ))

    weighted_gaps.sort(key=lambda x: -x[0])
    out = [s for _, s in weighted_gaps[:6]]

    # Surface remaining raw diffs the heuristics didn't classify
    for d in raw_diffs[:2]:
        if not any(d in o for o in out):
            out.append(d)

    if not out:
        out.append(
            "Looks structurally close. Open the diff HTML and use the Swipe / Difference "
            "tabs to spot subtle visual drifts (label positions, icon sizes, spacing)."
        )
    return out


def read_history(cache: Path) -> list[dict]:
    p = cache / "history.json"
    if not p.exists():
        return []
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []


def write_history(cache: Path, entry: dict, max_keep: int = 20) -> None:
    p = cache / "history.json"
    items = read_history(cache)
    items.append(entry)
    items = items[-max_keep:]
    p.write_text(json.dumps(items, indent=2), encoding="utf-8")


def load_template_recipe(target: Path) -> dict | None:
    """Look up the chosen template's deep design profile from the registry.

    Returns the profile dict (zones, icons, pills, edges, patterns, etc.) the
    LLM should match when relabeling. Returns None if the registry isn't built
    (run `profile_template.py --build-registry` first) or if `target` isn't
    in the bundled corpus (e.g. an externally-pinned reference).
    """
    registry_path = THIS_DIR.parent / "assets" / "reference-examples" / "template-profiles.json"
    if not registry_path.exists():
        return None
    try:
        reg = json.loads(registry_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return (reg.get("templates") or {}).get(target.name)


def fmt_delta(curr: float, prev: float | None) -> str:
    if prev is None:
        return "(first iteration)"
    delta = curr - prev
    arrow = "↑" if delta > 0 else ("↓" if delta < 0 else "→")
    return f"{arrow}{delta:+.1f} since last iteration"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("candidate", type=Path, help="the .drawio file you're iterating on")
    ap.add_argument("--target", type=Path, default=None,
                    help="explicit SAP reference template to converge toward (default: auto-select)")
    ap.add_argument("--refs-dir", type=Path, default=None,
                    help="directory of bundled SAP references (default: bundled assets)")
    ap.add_argument("--scale", type=float, default=1.0)
    ap.add_argument("--border", type=int, default=10)
    ap.add_argument("--min-score", type=float, default=90.0)
    ap.add_argument("--no-html", action="store_true",
                    help="skip the side-by-side HTML diff (faster, still gives PNGs + text)")
    ap.add_argument("--json", action="store_true", help="emit machine-readable JSON only")
    args = ap.parse_args()

    if not args.candidate.exists():
        print(f"candidate {args.candidate}: not found", file=sys.stderr)
        return 2

    refs_dir = args.refs_dir or (THIS_DIR.parent / "assets" / "reference-examples")
    if not refs_dir.exists():
        print(f"reference dir {refs_dir}: not found", file=sys.stderr)
        return 2

    cli = _render.find_drawio_cli()
    if not cli:
        print(
            "draw.io CLI not found — install draw.io desktop or set $DRAWIO_CLI.",
            file=sys.stderr,
        )
        return 2

    if args.target:
        target = args.target
        target_reason = "explicit --target"
        target_textual_score: float | None = None
    else:
        target, target_textual_score, target_reason = find_target(args.candidate, refs_dir)

    cache = cache_dir_for(args.candidate)
    cand_png = cache / f"{args.candidate.stem}.candidate.png"
    ref_png = cache / f"{target.stem}.reference.png"

    try:
        render_if_stale(cli, args.candidate, cand_png, args.scale, args.border)
        render_if_stale(cli, target, ref_png, args.scale, args.border)
    except RuntimeError as e:
        print(f"render failed: {e}", file=sys.stderr)
        return 2

    ref_fp = _compare.fingerprint(target)
    cand_fp = _compare.fingerprint(args.candidate)
    result = _compare.compare(ref_fp, cand_fp)

    history = read_history(cache)
    prev_score = history[-1]["score"] if history else None

    diff_html = None
    if not args.no_html:
        diff_html = write_diff_html(
            cache, args.candidate, target, cand_png, ref_png,
            result.score, result.breakdown, result.diffs, []
        )

    validator_groups = collect_validator_warnings(args.candidate)
    suggestions = actionable_suggestions(
        result.breakdown, ref_fp, cand_fp, result.diffs, validator_groups
    )

    entry = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "candidate": str(args.candidate),
        "target": str(target),
        "score": result.score,
        "breakdown": result.breakdown,
    }
    write_history(cache, entry)

    if args.json:
        out = {
            "candidate": str(args.candidate),
            "target": str(target),
            "target_reason": target_reason,
            "score": result.score,
            "previous_score": prev_score,
            "breakdown": result.breakdown,
            "diffs": result.diffs,
            "suggestions": suggestions,
            "candidate_png": str(cand_png),
            "reference_png": str(ref_png),
            "diff_html": str(diff_html) if diff_html else None,
            "passes": result.score >= args.min_score,
        }
        print(json.dumps(out, indent=2))
        return 0 if out["passes"] else 1

    # Look up the chosen target's design recipe from the precomputed registry
    target_recipe = load_template_recipe(target)

    # Human + LLM friendly text output
    print()
    print("─── SAP DIAGRAM ITERATION ───")
    print(f"candidate    : {args.candidate}")
    print(f"target       : {target.name}  ({target_reason})")
    print(f"score        : {result.score:.1f} / 100   {fmt_delta(result.score, prev_score)}")
    print(f"pass gate    : {args.min_score:.1f}   ({'PASS' if result.score >= args.min_score else 'BELOW — keep iterating'})")
    print()
    print("📷 Read these images with your vision tool to plan the next edit:")
    print(f"   candidate :  {cand_png}")
    print(f"   reference :  {ref_png}")
    if diff_html:
        print(f"   side-by-side HTML : {diff_html}")
    print()

    if target_recipe:
        print("🎯 SAP design recipe of your target template — preserve these patterns:")
        struct = target_recipe.get("structure_summary", {})
        if struct:
            print(
                f"   structure : {struct.get('top_level_zones', 0)} top-level zones, "
                f"{struct.get('nested_zones', 0)} nested, "
                f"{struct.get('cards', 0)} cards, "
                f"{struct.get('icons', 0)} icons, "
                f"{struct.get('pills', 0)} pills, "
                f"{struct.get('edges', 0)} edges"
            )
        if target_recipe.get("icon_sizes"):
            sizes = ", ".join(f"{n}×{s}" for s, n in list(target_recipe["icon_sizes"].items())[:4])
            print(f"   icon sizes: {sizes} — match these, do NOT exceed 48×48 unless ref does")
        if target_recipe.get("pill_vocab"):
            vocab = ", ".join(f"{p!r}" for p in target_recipe["pill_vocab"][:8])
            print(f"   pill vocab: {vocab}")
        eq = target_recipe.get("edge_quality", {})
        if eq.get("total"):
            print(
                f"   edges     : {eq['total']} total, "
                f"{eq.get('with_anchors', 0)} use entryX/exitX anchors, "
                f"{eq.get('orthogonal', 0)} orthogonalEdgeStyle "
                f"(your edges should follow the same proportions to avoid arrows-through-cards)"
            )
        if target_recipe.get("detected_patterns"):
            print(f"   patterns  : {', '.join(target_recipe['detected_patterns'][:6])}")
        zones = target_recipe.get("zones", [])
        top_zones = [z for z in zones if z.get("parent_id") in (None, "1")]
        if top_zones:
            zone_summary = "; ".join(
                f"{z.get('label', '?').strip() or '(unlabeled)':<30s} [{z.get('color_role', '?')}]"
                for z in top_zones[:6]
            )
            print(f"   top zones : {zone_summary}")
        print()

    # Lowest-scoring dimensions (top 5)
    print("⚠ Lowest-scoring dimensions (fix worst first):")
    sorted_dims = sorted(result.breakdown.items(), key=lambda kv: kv[1])[:6]
    for dim, val in sorted_dims:
        bar = "█" * int(val * 10) + "░" * (10 - int(val * 10))
        print(f"   {dim:14s}  {val*100:5.1f}%  {bar}")
    print()

    print("✏ Next concrete edit (do ONE, then re-run iterate.py):")
    for i, s in enumerate(suggestions, 1):
        # word-wrap at ~80 cols for readability
        prefix = f"   {i}. "
        cont = "      "
        words = s.split()
        line = prefix
        for w in words:
            if len(line) + len(w) + 1 > 88:
                print(line)
                line = cont + w
            else:
                line += (" " if line not in (prefix, cont) else "") + w
        print(line)
    print()

    if prev_score is not None:
        delta = result.score - prev_score
        if delta < -0.5:
            print(f"⏪ Last iteration regressed ({delta:+.1f}). Inspect the candidate vs the previous "
                  "version — consider rolling back the last edit if it wasn't intentional.")
        elif delta < 0.5:
            print("≈ Score barely moved. Pick a higher-impact suggestion above (the ones at the top "
                  "have the biggest weighted score gap).")
        else:
            print(f"✓ Score improved {delta:+.1f}. Keep going.")
        print()

    return 0 if result.score >= args.min_score else 1


if __name__ == "__main__":
    sys.exit(main())
