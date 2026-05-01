#!/usr/bin/env python3
"""Render a candidate + reference `.drawio` to PNG and produce a side-by-side
HTML review page.

Why this matters:
  The structural fingerprint score (`compare.py`) is necessary but
  insufficient for the last 20% of diagram polish. Two diagrams with
  similar fingerprints can look very different. The honest workflow is:

    scaffold → manual edit → render → side-by-side compare → iterate.

  This script collapses "render + compare + review" into one command so
  the human iteration loop is fast.

Usage:
  render_compare.py reference.drawio candidate.drawio
    → writes review.html plus reference.png + candidate.png next to it

  render_compare.py reference.drawio candidate.drawio \
      --out-dir .cache/review/agentic-ai/ --open

  render_compare.py reference.drawio candidate.drawio \
      --scale 1.5 --transparent

Exit code:
  0 — review HTML written
  1 — render or compare failed
  2 — usage / draw.io CLI not found
"""
from __future__ import annotations

import argparse
import html
import json
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

THIS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(THIS_DIR))

import render as _render        # noqa: E402  drawio CLI wrapper
import compare as _compare      # noqa: E402  fingerprint comparison


HTML_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>SAP Diagram Review – {title}</title>
  <style>
    :root {{
      color-scheme: light;
      --bg: #f5f6f7;
      --card: #ffffff;
      --border: #d5dadd;
      --primary: #0070f2;
      --good: #188918;
      --warn: #c35500;
      --bad: #d20a0a;
      --text: #1d2d3e;
      --muted: #556b82;
    }}
    body {{
      font-family: Helvetica, Arial, sans-serif;
      margin: 0;
      background: var(--bg);
      color: var(--text);
    }}
    header {{
      padding: 16px 24px;
      background: var(--card);
      border-bottom: 1px solid var(--border);
      display: flex;
      align-items: center;
      gap: 24px;
    }}
    header h1 {{
      margin: 0;
      font-size: 18px;
      font-weight: 600;
    }}
    header .score {{
      font-size: 32px;
      font-weight: 700;
      color: var(--score-color, var(--text));
    }}
    .layout {{
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 16px;
      padding: 16px 24px;
    }}
    .pane {{
      background: var(--card);
      border: 1px solid var(--border);
      border-radius: 8px;
      overflow: hidden;
    }}
    .pane h2 {{
      margin: 0;
      padding: 10px 14px;
      font-size: 13px;
      font-weight: 600;
      letter-spacing: 0.04em;
      text-transform: uppercase;
      color: var(--muted);
      border-bottom: 1px solid var(--border);
      background: #fafbfc;
    }}
    .pane figure {{
      margin: 0;
      padding: 12px;
      text-align: center;
      background: #fff;
    }}
    .pane figure img {{
      max-width: 100%;
      max-height: 75vh;
      border: 1px solid var(--border);
    }}
    .breakdown {{
      padding: 16px 24px;
    }}
    .breakdown table {{
      border-collapse: collapse;
      width: 100%;
      max-width: 760px;
      background: var(--card);
      border: 1px solid var(--border);
      border-radius: 8px;
      overflow: hidden;
    }}
    .breakdown th, .breakdown td {{
      padding: 8px 14px;
      border-bottom: 1px solid var(--border);
      font-size: 13px;
      text-align: left;
    }}
    .breakdown th {{
      background: #fafbfc;
      font-weight: 600;
      color: var(--muted);
      letter-spacing: 0.03em;
      text-transform: uppercase;
      font-size: 11px;
    }}
    .breakdown td.score {{
      text-align: right;
      font-variant-numeric: tabular-nums;
      width: 80px;
    }}
    .bar {{
      height: 6px;
      background: var(--border);
      border-radius: 3px;
      overflow: hidden;
    }}
    .bar > span {{
      display: block;
      height: 100%;
      background: var(--primary);
    }}
    .diffs {{
      padding: 0 24px 24px;
      max-width: 1024px;
    }}
    .diffs h3 {{
      font-size: 14px;
      font-weight: 600;
      color: var(--muted);
      letter-spacing: 0.04em;
      text-transform: uppercase;
      margin: 24px 0 8px;
    }}
    .diffs ul {{
      margin: 0;
      padding-left: 18px;
    }}
    .diffs li {{
      margin-bottom: 6px;
      font-size: 13px;
    }}
    .meta {{
      padding: 0 24px 24px;
      font-size: 12px;
      color: var(--muted);
    }}
  </style>
</head>
<body style="--score-color: {score_color}">
<header>
  <h1>SAP Diagram Review · {title}</h1>
  <div class="score">{score}</div>
  <span style="font-size:12px;color:var(--muted)">structural fidelity / 100</span>
</header>
<div class="layout">
  <section class="pane">
    <h2>Reference (target)</h2>
    <figure><img src="{ref_image}" alt="reference"></figure>
  </section>
  <section class="pane">
    <h2>Candidate (your diagram)</h2>
    <figure><img src="{cand_image}" alt="candidate"></figure>
  </section>
</div>
<section class="breakdown">
  <h3 style="font-size:14px;font-weight:600;color:var(--muted);text-transform:uppercase;letter-spacing:0.04em;margin:0 0 8px">Score breakdown</h3>
  <table>
    <thead><tr><th>Dimension</th><th class="score">Score</th><th>Bar</th></tr></thead>
    <tbody>
{breakdown_rows}
    </tbody>
  </table>
</section>
<section class="diffs">
  <h3>Notable differences</h3>
  {diffs_block}
  <h3>What to edit next</h3>
  <ul>
{actionable_block}
  </ul>
</section>
<section class="meta">
  <p><strong>Reference</strong>: {ref_path}</p>
  <p><strong>Candidate</strong>: {cand_path}</p>
  <p><strong>Generated</strong>: {timestamp}</p>
</section>
</body>
</html>
"""


def score_color(score: float) -> str:
    if score >= 95:
        return "var(--good)"
    if score >= 85:
        return "var(--primary)"
    if score >= 70:
        return "var(--warn)"
    return "var(--bad)"


def actionable_suggestions(breakdown: dict, ref_fp, cand_fp, diffs: list[str]) -> list[str]:
    """Map low-scoring fingerprint dimensions to concrete edit suggestions.

    Each rule is "if dimension X is below threshold, suggest a specific
    edit." This is the bridge from raw scoring to human-actionable advice.
    """
    out: list[str] = []
    if breakdown.get("page_bg", 1.0) < 1.0:
        out.append(
            "Set the canvas to white/transparent — remove "
            f"<code>pageBackgroundColor=\"{cand_fp.page_background or '?'}\"</code>"
            " from <mxGraphModel>. SAP diagrams are always on white."
        )
    if breakdown.get("canvas", 1.0) < 1.0:
        out.append(
            f"Resize canvas to {ref_fp.canvas_w}×{ref_fp.canvas_h} "
            f"(currently {cand_fp.canvas_w}×{cand_fp.canvas_h}). "
            "Open <em>Diagram → Page Setup</em> in draw.io."
        )
    if breakdown.get("zones", 1.0) < 0.7:
        out.append(
            f"Zone count differs (ref={ref_fp.zones}, cand={cand_fp.zones}). "
            "Add or remove rounded-corner area containers (arcSize=16, strokeWidth=1.5)."
        )
    if breakdown.get("zone_depth", 1.0) < 1.0:
        out.append(
            f"Zone nesting depth differs (ref={ref_fp.zone_depth}, cand={cand_fp.zone_depth}). "
            "Watch for cases where a focus zone (Joule, Identity Services) is nested inside BTP "
            "when the SAP reference puts them side-by-side."
        )
    if breakdown.get("icons", 1.0) < 0.7:
        out.append(
            f"Icon count differs (ref={ref_fp.icons}, cand={cand_fp.icons}). "
            "Use scripts/extract_icon.py to drop the missing BTP service icons."
        )
    if breakdown.get("pill_vocab", 1.0) < 1.0:
        if cand_fp.novelty_pill_count:
            out.append(
                f"Replace {cand_fp.novelty_pill_count} novelty pill verb(s) — pills should use "
                "TRUST/Authenticate/Authorization/A2A/MCP/ORD/HTTPS/OData/REST/SAML2/OIDC/SCIM, not "
                "PROMPT/ROUTE/CONTEXT/DELEGATE/INVOKE/FETCH."
            )
    if breakdown.get("edge_palette", 1.0) < 0.6:
        missing = sorted(set(ref_fp.edge_palette) - set(cand_fp.edge_palette))
        if missing:
            out.append(
                "Add SAP-mandated connector colors on edges: "
                f"<code>{', '.join(missing[:6])}</code>. "
                "trust=#CC00DC pink, auth=#188918 green, authorization=#5D36FF indigo, "
                "structural=#475E75 slate."
            )
    if breakdown.get("label_tokens", 1.0) < 0.6:
        out.append(
            "Label-token Jaccard is low — the diagram's visible text drifted from the reference. "
            "Restore or rename service-card labels to match the SAP scenario vocabulary."
        )
    if breakdown.get("grid_snap", 1.0) < 0.9:
        out.append(
            "Run <code>autofix.py --write</code> to snap geometry to the 10-px grid."
        )
    # Surface raw diffs we couldn't classify.
    for d in diffs[:3]:
        if d not in "".join(out):
            out.append(html.escape(d))
    if not out:
        out.append("Looks good. Open the file in draw.io desktop to verify visually.")
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("reference", type=Path)
    ap.add_argument("candidate", type=Path)
    ap.add_argument("--out-dir", type=Path, default=None,
                    help="output dir for the HTML and PNGs (default: alongside candidate)")
    ap.add_argument("--scale", type=float, default=1.0)
    ap.add_argument("--border", type=int, default=10)
    ap.add_argument("--transparent", action="store_true")
    ap.add_argument("--open", action="store_true", help="open the HTML in default browser")
    args = ap.parse_args()

    if not args.reference.exists():
        print(f"reference {args.reference}: not found", file=sys.stderr)
        return 1
    if not args.candidate.exists():
        print(f"candidate {args.candidate}: not found", file=sys.stderr)
        return 1

    cli = _render.find_drawio_cli()
    if not cli:
        print(
            "draw.io CLI not found — install draw.io desktop or set $DRAWIO_CLI.",
            file=sys.stderr,
        )
        return 2

    out_dir = args.out_dir or args.candidate.parent
    out_dir.mkdir(parents=True, exist_ok=True)

    ref_png = out_dir / f"{args.reference.stem}.reference.png"
    cand_png = out_dir / f"{args.candidate.stem}.candidate.png"

    rc = _render.render_one(cli, args.reference, ref_png, "png", args.scale, args.border, args.transparent, quiet=False)
    if rc != 0:
        print(f"reference render failed (rc={rc})", file=sys.stderr)
        return 1
    rc = _render.render_one(cli, args.candidate, cand_png, "png", args.scale, args.border, args.transparent, quiet=False)
    if rc != 0:
        print(f"candidate render failed (rc={rc})", file=sys.stderr)
        return 1

    ref_fp = _compare.fingerprint(args.reference)
    cand_fp = _compare.fingerprint(args.candidate)
    result = _compare.compare(ref_fp, cand_fp)

    breakdown_rows: list[str] = []
    for k, v in sorted(result.breakdown.items(), key=lambda kv: -kv[1]):
        pct = v * 100
        breakdown_rows.append(
            f'<tr><td>{html.escape(k)}</td>'
            f'<td class="score">{pct:.1f}</td>'
            f'<td><div class="bar"><span style="width: {pct:.1f}%"></span></div></td></tr>'
        )

    diffs_html = "<ul>"
    if result.diffs:
        for d in result.diffs:
            diffs_html += f"<li>{html.escape(d)}</li>"
    else:
        diffs_html += "<li>No notable structural differences detected.</li>"
    diffs_html += "</ul>"

    actionable = actionable_suggestions(result.breakdown, ref_fp, cand_fp, result.diffs)
    actionable_html = "\n".join(f"    <li>{a}</li>" for a in actionable)

    html_out = HTML_TEMPLATE.format(
        title=html.escape(args.candidate.stem),
        score=f"{result.score:.1f}",
        score_color=score_color(result.score),
        ref_image=html.escape(ref_png.name),
        cand_image=html.escape(cand_png.name),
        ref_path=html.escape(str(args.reference)),
        cand_path=html.escape(str(args.candidate)),
        timestamp=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
        breakdown_rows="\n".join(breakdown_rows),
        diffs_block=diffs_html,
        actionable_block=actionable_html,
    )

    review_html = out_dir / "review.html"
    review_html.write_text(html_out, encoding="utf-8")

    summary = {
        "reference": str(args.reference),
        "candidate": str(args.candidate),
        "score": result.score,
        "breakdown": result.breakdown,
        "diffs": result.diffs,
        "ref_image": str(ref_png),
        "cand_image": str(cand_png),
        "review_html": str(review_html),
    }
    (out_dir / "review.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")

    print(f"score      : {result.score:.1f}/100")
    print(f"reference  : {ref_png}")
    print(f"candidate  : {cand_png}")
    print(f"review     : {review_html}")
    if args.open:
        try:
            subprocess.run(["open", str(review_html)], check=False)
        except FileNotFoundError:
            pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
