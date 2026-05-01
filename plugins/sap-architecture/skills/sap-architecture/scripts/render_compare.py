#!/usr/bin/env python3
"""Render a candidate + reference `.drawio` to PNG and produce a side-by-side
HTML review page with overlay-swipe, hover-zoom, and tabs for the different
comparison modes.

Why this matters:
  The structural fingerprint score (`compare.py`) is necessary but
  insufficient for the last 20% of diagram polish. Two diagrams with
  similar fingerprints can look very different. The honest workflow is:

    scaffold → manual edit → render → side-by-side compare → iterate.

  This script collapses "render + compare + review" into one command so
  the human iteration loop is fast.

  The HTML supports four review modes:
    1. Side-by-side: classic two-pane comparison.
    2. Overlay slider: drag a slider to fade between reference and
       candidate. Catches subtle position/size drifts.
    3. Swipe (curtain): vertical dividing line you drag — left half
       reference, right half candidate. Fastest way to spot zone-level
       differences.
    4. Difference: stacked images with subtraction blend mode (browser-
       native), no Pillow dependency.

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


HTML_TEMPLATE = r"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>SAP Diagram Review – __TITLE__</title>
  <style>
    :root {
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
      --shadow: 0 2px 8px rgba(29, 45, 62, 0.06);
    }
    * { box-sizing: border-box; }
    body {
      font-family: Helvetica, Arial, sans-serif;
      margin: 0;
      background: var(--bg);
      color: var(--text);
      line-height: 1.45;
    }
    header {
      padding: 16px 24px;
      background: var(--card);
      border-bottom: 1px solid var(--border);
      display: flex;
      align-items: center;
      gap: 20px;
      flex-wrap: wrap;
    }
    header h1 {
      margin: 0;
      font-size: 17px;
      font-weight: 600;
      flex: 1;
      min-width: 280px;
    }
    .badge {
      display: inline-block;
      padding: 2px 8px;
      font-size: 11px;
      letter-spacing: 0.04em;
      text-transform: uppercase;
      background: var(--bg);
      color: var(--muted);
      border-radius: 4px;
      margin-left: 8px;
    }
    .score-pill {
      display: flex;
      align-items: center;
      gap: 14px;
      padding: 10px 18px;
      background: var(--score-bg, var(--bg));
      border: 1px solid var(--score-border, var(--border));
      border-radius: 999px;
    }
    .score-pill .num {
      font-size: 28px;
      font-weight: 700;
      color: var(--score-color, var(--text));
      font-variant-numeric: tabular-nums;
    }
    .score-pill .lbl {
      font-size: 11px;
      color: var(--muted);
      text-transform: uppercase;
      letter-spacing: 0.05em;
    }
    .actions {
      display: flex;
      gap: 8px;
    }
    .actions a, .actions button {
      display: inline-flex;
      align-items: center;
      gap: 6px;
      padding: 8px 14px;
      font: inherit;
      font-size: 13px;
      border: 1px solid var(--border);
      background: var(--card);
      color: var(--text);
      border-radius: 6px;
      text-decoration: none;
      cursor: pointer;
      transition: background 80ms;
    }
    .actions a:hover, .actions button:hover {
      background: var(--bg);
    }
    .actions a.primary, .actions button.primary {
      background: var(--primary);
      color: white;
      border-color: var(--primary);
    }
    .actions a.primary:hover, .actions button.primary:hover {
      filter: brightness(1.06);
    }

    nav.modes {
      padding: 0 24px;
      background: var(--card);
      border-bottom: 1px solid var(--border);
      display: flex;
      gap: 4px;
    }
    nav.modes button {
      background: transparent;
      border: none;
      padding: 12px 16px;
      font-size: 13px;
      font-weight: 500;
      color: var(--muted);
      cursor: pointer;
      border-bottom: 2px solid transparent;
      margin-bottom: -1px;
      font-family: inherit;
    }
    nav.modes button.active {
      color: var(--primary);
      border-bottom-color: var(--primary);
    }
    nav.modes button:hover { color: var(--text); }

    .stage {
      padding: 16px 24px;
    }
    .panel {
      background: var(--card);
      border: 1px solid var(--border);
      border-radius: 10px;
      box-shadow: var(--shadow);
      overflow: hidden;
    }

    /* Mode: side-by-side */
    .mode { display: none; }
    .mode.active { display: block; }
    .sbs {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 16px;
    }
    @media (max-width: 1024px) {
      .sbs { grid-template-columns: 1fr; }
    }
    .pane h2 {
      margin: 0;
      padding: 10px 14px;
      font-size: 12px;
      font-weight: 600;
      letter-spacing: 0.05em;
      text-transform: uppercase;
      color: var(--muted);
      border-bottom: 1px solid var(--border);
      background: #fafbfc;
      display: flex;
      justify-content: space-between;
      align-items: center;
    }
    .pane h2 .who {
      display: flex;
      align-items: center;
      gap: 8px;
    }
    .pane h2 .who::before {
      content: "";
      width: 8px; height: 8px; border-radius: 50%;
    }
    .pane h2.ref .who::before { background: var(--good); }
    .pane h2.cand .who::before { background: var(--primary); }
    .pane figure {
      margin: 0;
      padding: 12px;
      background: #fff;
      text-align: center;
    }
    .pane figure img {
      max-width: 100%;
      max-height: 78vh;
      border: 1px solid var(--border);
      cursor: zoom-in;
    }

    /* Mode: overlay slider */
    .overlay-wrap {
      padding: 14px;
      text-align: center;
      background: #fff;
    }
    .overlay-stage {
      position: relative;
      display: inline-block;
      max-width: 100%;
    }
    .overlay-stage img {
      display: block;
      max-width: 100%;
      max-height: 78vh;
      border: 1px solid var(--border);
    }
    .overlay-stage img.cand {
      position: absolute;
      top: 0; left: 0;
      pointer-events: none;
    }
    .overlay-controls {
      padding: 14px 24px 18px;
      display: flex;
      align-items: center;
      gap: 14px;
      justify-content: center;
      background: #fafbfc;
      border-top: 1px solid var(--border);
    }
    .overlay-controls label {
      font-size: 13px;
      color: var(--muted);
    }
    .overlay-controls input[type=range] {
      width: 280px;
    }
    .opacity-readout {
      width: 56px;
      text-align: right;
      font-variant-numeric: tabular-nums;
      color: var(--text);
      font-weight: 600;
    }

    /* Mode: swipe / curtain */
    .swipe-wrap {
      padding: 14px;
      background: #fff;
      text-align: center;
    }
    .swipe-stage {
      position: relative;
      display: inline-block;
      max-width: 100%;
      cursor: ew-resize;
      user-select: none;
    }
    .swipe-stage img {
      display: block;
      max-width: 100%;
      max-height: 78vh;
      border: 1px solid var(--border);
    }
    .swipe-stage .clip {
      position: absolute;
      top: 0; left: 0;
      bottom: 0;
      overflow: hidden;
      width: 50%;
      border-right: 2px solid var(--primary);
      pointer-events: none;
    }
    .swipe-stage .clip img {
      max-width: none;
      width: auto;
    }
    .swipe-handle {
      position: absolute;
      top: 50%; transform: translateY(-50%);
      width: 32px; height: 32px;
      background: var(--primary);
      color: white;
      border-radius: 50%;
      display: flex;
      align-items: center;
      justify-content: center;
      font-size: 14px;
      font-weight: 700;
      cursor: ew-resize;
      box-shadow: 0 2px 8px rgba(0, 112, 242, 0.4);
      pointer-events: auto;
    }
    .swipe-labels {
      display: flex;
      justify-content: space-between;
      padding: 8px 24px;
      font-size: 11px;
      letter-spacing: 0.05em;
      text-transform: uppercase;
      color: var(--muted);
      background: #fafbfc;
      border-top: 1px solid var(--border);
    }

    /* Mode: difference (CSS blend) */
    .diff-wrap {
      padding: 14px;
      background: #1d2d3e;
      text-align: center;
    }
    .diff-stage {
      position: relative;
      display: inline-block;
    }
    .diff-stage img {
      max-width: 100%;
      max-height: 78vh;
      display: block;
    }
    .diff-stage .top {
      position: absolute;
      top: 0; left: 0;
      mix-blend-mode: difference;
    }
    .diff-note {
      padding: 12px 24px;
      background: #1d2d3e;
      color: #d5dadd;
      font-size: 12px;
      text-align: center;
      border-top: 1px solid #354a5f;
    }

    /* Score breakdown */
    .breakdown {
      padding: 18px 24px 8px;
    }
    .breakdown h3 {
      margin: 0 0 10px;
      font-size: 13px;
      font-weight: 600;
      color: var(--muted);
      letter-spacing: 0.05em;
      text-transform: uppercase;
    }
    .breakdown table {
      border-collapse: collapse;
      width: 100%;
      max-width: 920px;
      background: var(--card);
      border: 1px solid var(--border);
      border-radius: 8px;
      overflow: hidden;
    }
    .breakdown th, .breakdown td {
      padding: 9px 14px;
      border-bottom: 1px solid var(--border);
      font-size: 13px;
      text-align: left;
    }
    .breakdown th {
      background: #fafbfc;
      font-weight: 600;
      color: var(--muted);
      letter-spacing: 0.04em;
      text-transform: uppercase;
      font-size: 11px;
    }
    .breakdown td.score {
      text-align: right;
      font-variant-numeric: tabular-nums;
      width: 80px;
      font-weight: 600;
    }
    .breakdown td.bar-cell {
      width: 280px;
    }
    .bar {
      height: 7px;
      background: #eaecee;
      border-radius: 3px;
      overflow: hidden;
    }
    .bar > span {
      display: block;
      height: 100%;
      transition: width 200ms;
    }
    .bar > span.good   { background: var(--good); }
    .bar > span.fine   { background: var(--primary); }
    .bar > span.warn   { background: var(--warn); }
    .bar > span.bad    { background: var(--bad); }

    /* Suggestions and diffs */
    .insights {
      padding: 18px 24px 28px;
      max-width: 1180px;
    }
    .insights h3 {
      margin: 18px 0 8px;
      font-size: 13px;
      font-weight: 600;
      color: var(--muted);
      letter-spacing: 0.05em;
      text-transform: uppercase;
    }
    .insights ul {
      margin: 0;
      padding: 0;
      list-style: none;
    }
    .insights li {
      padding: 12px 14px;
      margin-bottom: 8px;
      background: var(--card);
      border: 1px solid var(--border);
      border-left: 3px solid var(--primary);
      border-radius: 6px;
      font-size: 13px;
    }
    .insights li.diff {
      border-left-color: var(--warn);
    }
    .insights code {
      background: #f5f6f7;
      padding: 1px 6px;
      border-radius: 3px;
      font-size: 12px;
      font-family: Menlo, Consolas, monospace;
    }
    .insights .empty {
      color: var(--muted);
      font-style: italic;
    }

    /* Lightbox */
    .lightbox {
      position: fixed;
      inset: 0;
      background: rgba(29, 45, 62, 0.85);
      display: none;
      align-items: center;
      justify-content: center;
      cursor: zoom-out;
      z-index: 50;
    }
    .lightbox.active { display: flex; }
    .lightbox img {
      max-width: 95vw;
      max-height: 95vh;
    }

    /* Meta footer */
    .meta {
      padding: 14px 24px 30px;
      font-size: 12px;
      color: var(--muted);
    }
    .meta p {
      margin: 4px 0;
    }
    .meta code {
      background: var(--card);
      border: 1px solid var(--border);
      padding: 1px 6px;
      border-radius: 3px;
      font-size: 11px;
    }
  </style>
</head>
<body>
<header>
  <h1>SAP Diagram Review · __TITLE__ <span class="badge">__BADGE_LABEL__</span></h1>
  <div class="score-pill" style="--score-color: __SCORE_COLOR__; --score-bg: __SCORE_BG__; --score-border: __SCORE_BORDER__">
    <span class="num">__SCORE__</span>
    <span class="lbl">structural fidelity / 100</span>
  </div>
  <div class="actions">
    <a class="primary" href="__CAND_DRAWIO_URI__" title="Open the candidate in draw.io desktop">Open candidate in draw.io</a>
    <a href="__REF_DRAWIO_URI__" title="Open the reference template in draw.io desktop">Open reference</a>
  </div>
</header>

<nav class="modes" id="mode-nav">
  <button data-mode="sbs" class="active">Side-by-side</button>
  <button data-mode="overlay">Overlay slider</button>
  <button data-mode="swipe">Swipe</button>
  <button data-mode="diff">Difference</button>
</nav>

<div class="stage">
  <!-- Side-by-side -->
  <div class="mode active" id="m-sbs">
    <div class="sbs">
      <section class="panel pane">
        <h2 class="ref"><span class="who">Reference (target)</span><span style="font-weight:400;text-transform:none;letter-spacing:0;font-size:11px">__REF_NAME__</span></h2>
        <figure><img src="__REF_IMG__" alt="reference" data-zoom></figure>
      </section>
      <section class="panel pane">
        <h2 class="cand"><span class="who">Candidate (your diagram)</span><span style="font-weight:400;text-transform:none;letter-spacing:0;font-size:11px">__CAND_NAME__</span></h2>
        <figure><img src="__CAND_IMG__" alt="candidate" data-zoom></figure>
      </section>
    </div>
  </div>

  <!-- Overlay slider -->
  <div class="mode" id="m-overlay">
    <section class="panel">
      <div class="overlay-wrap">
        <div class="overlay-stage">
          <img src="__REF_IMG__" alt="reference">
          <img src="__CAND_IMG__" alt="candidate" class="cand" id="overlay-cand" style="opacity: 0.5">
        </div>
      </div>
      <div class="overlay-controls">
        <label>Reference</label>
        <input type="range" min="0" max="100" value="50" id="overlay-slider">
        <label>Candidate</label>
        <span class="opacity-readout" id="overlay-readout">50%</span>
      </div>
    </section>
  </div>

  <!-- Swipe / curtain -->
  <div class="mode" id="m-swipe">
    <section class="panel">
      <div class="swipe-wrap">
        <div class="swipe-stage" id="swipe-stage">
          <img src="__CAND_IMG__" alt="candidate" id="swipe-bg">
          <div class="clip" id="swipe-clip">
            <img src="__REF_IMG__" alt="reference" id="swipe-fg">
          </div>
          <div class="swipe-handle" id="swipe-handle">↔</div>
        </div>
      </div>
      <div class="swipe-labels">
        <span>Reference (left of line)</span>
        <span>Candidate (right of line)</span>
      </div>
    </section>
  </div>

  <!-- Difference (CSS blend) -->
  <div class="mode" id="m-diff">
    <section class="panel">
      <div class="diff-wrap">
        <div class="diff-stage">
          <img src="__REF_IMG__" alt="reference">
          <img src="__CAND_IMG__" alt="candidate" class="top">
        </div>
      </div>
      <p class="diff-note">Black areas = identical pixels. Bright areas = differences. Uses the browser's <code>mix-blend-mode: difference</code>.</p>
    </section>
  </div>
</div>

<section class="breakdown">
  <h3>Score breakdown — what to fix in priority order</h3>
  <table>
    <thead><tr><th>Dimension</th><th class="score">Score</th><th class="bar-cell">Bar</th></tr></thead>
    <tbody>
__BREAKDOWN_ROWS__
    </tbody>
  </table>
</section>

<section class="insights">
  <h3>Actionable suggestions</h3>
  <ul>
__ACTIONABLE_BLOCK__
  </ul>
  <h3>Notable structural diffs</h3>
__DIFFS_BLOCK__
</section>

<section class="meta">
  <p><strong>Reference</strong> · <code>__REF_PATH__</code></p>
  <p><strong>Candidate</strong> · <code>__CAND_PATH__</code></p>
  <p>Generated <code>__TIMESTAMP__</code>. After editing the candidate in draw.io desktop, re-run <code>render_compare.py</code> to refresh this review.</p>
</section>

<div class="lightbox" id="lightbox"><img id="lightbox-img" alt="zoomed"></div>

<script>
// Mode switcher
document.getElementById('mode-nav').addEventListener('click', e => {
  if (e.target.tagName !== 'BUTTON') return;
  const target = e.target.dataset.mode;
  document.querySelectorAll('#mode-nav button').forEach(b => b.classList.toggle('active', b.dataset.mode === target));
  document.querySelectorAll('.mode').forEach(m => m.classList.toggle('active', m.id === 'm-' + target));
});

// Overlay slider
const overlaySlider = document.getElementById('overlay-slider');
const overlayCand = document.getElementById('overlay-cand');
const overlayReadout = document.getElementById('overlay-readout');
overlaySlider.addEventListener('input', () => {
  const v = overlaySlider.value;
  overlayCand.style.opacity = v / 100;
  overlayReadout.textContent = v + '%';
});

// Swipe / curtain — keep reference image fully sized in the clip; resize on window/image load
const swipeStage = document.getElementById('swipe-stage');
const swipeClip = document.getElementById('swipe-clip');
const swipeFg = document.getElementById('swipe-fg');
const swipeBg = document.getElementById('swipe-bg');
const swipeHandle = document.getElementById('swipe-handle');

function syncSwipeFgSize() {
  const r = swipeBg.getBoundingClientRect();
  swipeFg.style.width = r.width + 'px';
  swipeFg.style.height = r.height + 'px';
}
swipeBg.addEventListener('load', syncSwipeFgSize);
window.addEventListener('resize', syncSwipeFgSize);

let dragging = false;
function setSwipe(clientX) {
  const r = swipeStage.getBoundingClientRect();
  let pct = ((clientX - r.left) / r.width) * 100;
  pct = Math.max(0, Math.min(100, pct));
  swipeClip.style.width = pct + '%';
  swipeHandle.style.left = pct + '%';
}
swipeStage.addEventListener('mousedown', e => { dragging = true; setSwipe(e.clientX); e.preventDefault(); });
window.addEventListener('mousemove', e => { if (dragging) setSwipe(e.clientX); });
window.addEventListener('mouseup', () => { dragging = false; });
swipeStage.addEventListener('touchstart', e => { dragging = true; setSwipe(e.touches[0].clientX); }, { passive: true });
window.addEventListener('touchmove', e => { if (dragging) setSwipe(e.touches[0].clientX); }, { passive: true });
window.addEventListener('touchend', () => { dragging = false; });
// Initialize handle position
window.addEventListener('load', () => {
  syncSwipeFgSize();
  const r = swipeStage.getBoundingClientRect();
  swipeHandle.style.left = '50%';
});

// Lightbox click-to-zoom on side-by-side images
const lightbox = document.getElementById('lightbox');
const lightboxImg = document.getElementById('lightbox-img');
document.querySelectorAll('img[data-zoom]').forEach(img => {
  img.addEventListener('click', () => {
    lightboxImg.src = img.src;
    lightbox.classList.add('active');
  });
});
lightbox.addEventListener('click', () => lightbox.classList.remove('active'));

// Keyboard shortcuts: 1/2/3/4 to switch modes, Esc closes lightbox
document.addEventListener('keydown', e => {
  if (e.key === 'Escape') lightbox.classList.remove('active');
  const idx = ['1', '2', '3', '4'].indexOf(e.key);
  if (idx >= 0) {
    const modes = ['sbs', 'overlay', 'swipe', 'diff'];
    document.querySelector(`#mode-nav button[data-mode=${modes[idx]}]`).click();
  }
});
</script>
</body>
</html>
"""


def score_color(score: float) -> tuple[str, str, str]:
    """Return (color, bg, border) tuple for the score pill."""
    if score >= 95:
        return ("#188918", "#F5FAE5", "#C6E5C8")
    if score >= 85:
        return ("#0070F2", "#EBF8FF", "#B8DCFC")
    if score >= 70:
        return ("#C35500", "#FFF8D6", "#F2D8A6")
    return ("#D20A0A", "#FFEAF4", "#F5C5C0")


def bar_class(pct: float) -> str:
    if pct >= 95:
        return "good"
    if pct >= 80:
        return "fine"
    if pct >= 60:
        return "warn"
    return "bad"


def actionable_suggestions(breakdown: dict, ref_fp, cand_fp, diffs: list[str]) -> list[str]:
    """Map low-scoring fingerprint dimensions to concrete edit suggestions.

    Each rule is "if dimension X is below threshold, suggest a specific
    edit." This is the bridge from raw scoring to human-actionable advice.
    """
    out: list[str] = []
    if breakdown.get("page_bg", 1.0) < 1.0:
        out.append(
            "Set the canvas to white or transparent — remove "
            f"<code>pageBackgroundColor=\"{cand_fp.page_background or '?'}\"</code>"
            " from <code>&lt;mxGraphModel&gt;</code>. SAP diagrams are always on white."
        )
    if breakdown.get("canvas", 1.0) < 1.0:
        out.append(
            f"Resize canvas to <code>{ref_fp.canvas_w}×{ref_fp.canvas_h}</code> "
            f"(currently <code>{cand_fp.canvas_w}×{cand_fp.canvas_h}</code>). "
            "In draw.io: <em>Diagram → Page Setup → Custom</em>."
        )
    if breakdown.get("zones", 1.0) < 0.7:
        delta = abs(ref_fp.zones - cand_fp.zones)
        verb = "add" if cand_fp.zones < ref_fp.zones else "remove"
        out.append(
            f"Zone count differs (ref={ref_fp.zones}, cand={cand_fp.zones}). "
            f"{verb.capitalize()} {delta} rounded-corner area container(s) "
            "(<code>arcSize=16</code>, <code>strokeWidth=1.5</code>)."
        )
    if breakdown.get("zone_depth", 1.0) < 1.0:
        out.append(
            f"Zone nesting depth differs (ref={ref_fp.zone_depth}, cand={cand_fp.zone_depth}). "
            "Watch for cases where a focus zone (Joule, Identity Services) is nested inside BTP "
            "when the SAP reference puts them side-by-side."
        )
    if breakdown.get("icons", 1.0) < 0.7:
        delta = abs(ref_fp.icons - cand_fp.icons)
        verb = "add" if cand_fp.icons < ref_fp.icons else "remove"
        out.append(
            f"Icon count differs (ref={ref_fp.icons}, cand={cand_fp.icons}). "
            f"{verb.capitalize()} {delta} BTP service icon(s) using "
            "<code>scripts/extract_icon.py \"&lt;service&gt;\" --x &lt;X&gt; --y &lt;Y&gt;</code>."
        )
    if breakdown.get("pill_vocab", 1.0) < 1.0:
        if cand_fp.novelty_pill_count:
            out.append(
                f"Replace {cand_fp.novelty_pill_count} novelty pill verb(s). "
                "SAP-canonical pill labels: <code>TRUST</code>, <code>Authenticate</code>, "
                "<code>Authorization</code>, <code>A2A</code>, <code>MCP</code>, "
                "<code>ORD</code>, <code>HTTPS</code>, <code>OData/REST</code>, "
                "<code>SAML2/OIDC</code>, <code>SCIM</code>. Avoid "
                "PROMPT/ROUTE/CONTEXT/DELEGATE/INVOKE/FETCH."
            )
    if breakdown.get("edge_palette", 1.0) < 0.6:
        missing = sorted(set(ref_fp.edge_palette) - set(cand_fp.edge_palette))
        if missing:
            swatch = " ".join(
                f'<span style="display:inline-block;width:14px;height:14px;background:{c};'
                f'border-radius:3px;border:1px solid var(--border);vertical-align:middle"></span>'
                f' <code>{c}</code>'
                for c in missing[:6]
            )
            out.append(
                f"Add SAP-mandated connector colors on edges: {swatch}. "
                "trust=<code>#CC00DC</code> pink · auth=<code>#188918</code> green · "
                "authorization=<code>#5D36FF</code> indigo · structural=<code>#475E75</code> slate."
            )
    if breakdown.get("label_tokens", 1.0) < 0.6:
        out.append(
            "Label-token Jaccard is low — visible text drifted from the reference. "
            "Restore or rename service-card labels to match the SAP scenario vocabulary."
        )
    if breakdown.get("grid_snap", 1.0) < 0.9:
        out.append(
            "Geometry off the 10-px grid. Run "
            "<code>autofix.py --write &lt;file&gt;</code> to snap automatically."
        )
    # Surface raw diffs we couldn't classify into specific advice
    for d in diffs[:3]:
        if not any(d in o for o in out):
            out.append(html.escape(d))
    if not out:
        out.append("Looks structurally close. Use the <strong>Swipe</strong> or "
                   "<strong>Difference</strong> tabs above to spot subtle visual drifts.")
    return out


def to_file_uri(path: Path) -> str:
    """Convert an absolute path to a file:// URI for browser links."""
    p = path.resolve()
    # macOS/Linux: prepend /// (file:///abs/path)
    return "file://" + str(p)


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
    for k, v in sorted(result.breakdown.items(), key=lambda kv: kv[1]):
        pct = v * 100
        cls = bar_class(pct)
        breakdown_rows.append(
            f'<tr><td>{html.escape(k)}</td>'
            f'<td class="score">{pct:.1f}</td>'
            f'<td class="bar-cell"><div class="bar"><span class="{cls}" style="width: {pct:.1f}%"></span></div></td></tr>'
        )

    if result.diffs:
        diffs_html = "<ul>"
        for d in result.diffs:
            diffs_html += f'<li class="diff">{html.escape(d)}</li>'
        diffs_html += "</ul>"
    else:
        diffs_html = '<ul><li class="empty">No notable structural differences detected.</li></ul>'

    actionable = actionable_suggestions(result.breakdown, ref_fp, cand_fp, result.diffs)
    actionable_html = "\n".join(f"    <li>{a}</li>" for a in actionable)

    color, bg, border = score_color(result.score)

    badge_label = "PASS ≥ 90" if result.score >= 90 else (
        "Near-miss" if result.score >= 80 else (
            "Below 80 — needs structural work" if result.score >= 60 else "Far from target"
        )
    )

    placeholders = {
        "TITLE": html.escape(args.candidate.stem),
        "BADGE_LABEL": html.escape(badge_label),
        "SCORE": f"{result.score:.1f}",
        "SCORE_COLOR": color,
        "SCORE_BG": bg,
        "SCORE_BORDER": border,
        "REF_NAME": html.escape(args.reference.name),
        "CAND_NAME": html.escape(args.candidate.name),
        "REF_IMG": html.escape(ref_png.name),
        "CAND_IMG": html.escape(cand_png.name),
        "REF_DRAWIO_URI": html.escape(to_file_uri(args.reference)),
        "CAND_DRAWIO_URI": html.escape(to_file_uri(args.candidate)),
        "REF_PATH": html.escape(str(args.reference)),
        "CAND_PATH": html.escape(str(args.candidate)),
        "TIMESTAMP": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
        "BREAKDOWN_ROWS": "\n".join(breakdown_rows),
        "DIFFS_BLOCK": diffs_html,
        "ACTIONABLE_BLOCK": actionable_html,
    }

    html_out = HTML_TEMPLATE
    for key, val in placeholders.items():
        html_out = html_out.replace(f"__{key}__", val)

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

    print(f"score      : {result.score:.1f}/100  ({badge_label})")
    print(f"reference  : {ref_png}")
    print(f"candidate  : {cand_png}")
    print(f"review     : {review_html}")
    print(f"           open with: open {review_html}")
    if args.open:
        try:
            subprocess.run(["open", str(review_html)], check=False)
        except FileNotFoundError:
            pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
