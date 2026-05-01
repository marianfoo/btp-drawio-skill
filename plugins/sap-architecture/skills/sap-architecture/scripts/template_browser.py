#!/usr/bin/env python3
"""Pre-render every bundled SAP reference template to PNG and emit an HTML
gallery so a human can browse the catalog and pick the right starting
template visually.

The selector ranks templates from a text prompt, but humans pick faster
when they can see a thumbnail. This is especially useful when the
selector is unsure or when the prompt is vague.

Usage:
  template_browser.py
  template_browser.py --out-dir .cache/template-browser/
  template_browser.py --thumbs-only  # skip HTML, just render PNGs

Output:
  .cache/template-browser/<template>.png      (one per template)
  .cache/template-browser/index.html          (clickable gallery)

Exit code:
  0 — gallery built
  1 — render failed for one or more templates
  2 — usage / draw.io CLI not found
"""
from __future__ import annotations

import argparse
import html
import json
import sys
from pathlib import Path

THIS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(THIS_DIR))

import render as _render  # noqa: E402

ASSETS_DIR = THIS_DIR.parent / "assets" / "reference-examples"


HTML_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>SAP Reference Template Gallery</title>
<style>
  body {{
    font-family: Helvetica, Arial, sans-serif;
    margin: 0;
    background: #f5f6f7;
    color: #1d2d3e;
  }}
  header {{
    padding: 16px 24px;
    background: #fff;
    border-bottom: 1px solid #d5dadd;
  }}
  header h1 {{ margin: 0; font-size: 18px; }}
  header p {{ margin: 4px 0 0; font-size: 13px; color: #556b82; }}
  .filter {{
    padding: 12px 24px;
    background: #fff;
    border-bottom: 1px solid #d5dadd;
  }}
  .filter input {{
    width: 380px;
    padding: 6px 10px;
    border: 1px solid #d5dadd;
    border-radius: 4px;
    font-size: 13px;
  }}
  .grid {{
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(360px, 1fr));
    gap: 16px;
    padding: 16px 24px;
  }}
  .card {{
    background: #fff;
    border: 1px solid #d5dadd;
    border-radius: 8px;
    overflow: hidden;
  }}
  .card .meta {{
    padding: 10px 14px;
    border-bottom: 1px solid #d5dadd;
  }}
  .card .meta strong {{ font-size: 13px; }}
  .card .meta .domain {{
    display: inline-block;
    margin-left: 6px;
    padding: 2px 6px;
    font-size: 11px;
    background: #ebf8ff;
    color: #0070f2;
    border-radius: 4px;
  }}
  .card .meta .level {{
    display: inline-block;
    margin-left: 4px;
    padding: 2px 6px;
    font-size: 11px;
    background: #f5f6f7;
    color: #556b82;
    border-radius: 4px;
  }}
  .card .meta .title {{
    display: block;
    margin-top: 4px;
    color: #556b82;
    font-size: 12px;
  }}
  .card figure {{
    margin: 0;
    background: #fff;
    aspect-ratio: 1.4 / 1;
    display: flex;
    align-items: center;
    justify-content: center;
    overflow: hidden;
  }}
  .card figure img {{ width: 100%; height: 100%; object-fit: contain; }}
  .card .actions {{
    padding: 8px 14px;
    border-top: 1px solid #d5dadd;
    font-size: 12px;
    color: #556b82;
  }}
  code {{ background: #f5f6f7; padding: 1px 5px; border-radius: 3px; font-size: 11px; }}
</style>
</head>
<body>
<header>
  <h1>SAP Reference Template Gallery</h1>
  <p>{count} bundled SAP templates · click a thumbnail to open the .drawio source · use <code>scaffold_diagram.py --template &lt;name&gt;</code> to start a new diagram from one</p>
</header>
<div class="filter">
  <input type="text" id="filter" placeholder="filter by name, domain, family, level…" oninput="filterCards()">
</div>
<section class="grid" id="grid">
{cards}
</section>
<script>
function filterCards() {{
  const q = document.getElementById('filter').value.toLowerCase();
  for (const card of document.querySelectorAll('.card')) {{
    const blob = card.dataset.blob;
    card.style.display = blob.includes(q) ? '' : 'none';
  }}
}}
</script>
</body>
</html>
"""


CARD_TEMPLATE = """<div class="card" data-blob="{blob}">
  <figure><a href="{drawio_link}"><img src="{thumb}" alt="{name}" loading="lazy"></a></figure>
  <div class="meta">
    <strong>{name}</strong>
    <span class="domain">{domain}</span>
    <span class="level">{level}</span>
    <span class="title">{title}</span>
  </div>
  <div class="actions">
    <code>scaffold_diagram.py --template {name} --out my-diagram.drawio</code>
  </div>
</div>"""


def load_metadata() -> dict:
    md_path = ASSETS_DIR / "template-metadata.json"
    if not md_path.exists():
        return {"templates": {}}
    return json.loads(md_path.read_text(encoding="utf-8"))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-dir", type=Path, default=Path(".cache/template-browser"))
    ap.add_argument("--thumbs-only", action="store_true",
                    help="skip the HTML gallery; just render PNGs")
    ap.add_argument("--scale", type=float, default=0.6,
                    help="render scale for thumbnails (smaller = faster)")
    ap.add_argument("--force", action="store_true",
                    help="re-render existing PNGs (default: skip if PNG newer than .drawio)")
    args = ap.parse_args()

    cli = _render.find_drawio_cli()
    if not cli:
        print("draw.io CLI not found", file=sys.stderr)
        return 2

    out_dir = args.out_dir.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    if not ASSETS_DIR.exists():
        print(f"reference-examples directory missing: {ASSETS_DIR}", file=sys.stderr)
        return 1

    metadata = load_metadata().get("templates", {})
    templates = sorted(ASSETS_DIR.glob("*.drawio"))
    print(f"rendering {len(templates)} templates to {out_dir} ...", file=sys.stderr)

    failures = 0
    cards: list[str] = []
    for src in templates:
        thumb = out_dir / (src.stem + ".png")
        if not thumb.exists() or args.force or thumb.stat().st_mtime < src.stat().st_mtime:
            rc = _render.render_one(
                cli, src, thumb,
                fmt="png", scale=args.scale, border=10,
                transparent=False, quiet=True,
            )
            if rc != 0:
                failures += 1
                print(f"  failed: {src.name}", file=sys.stderr)
                continue
            print(f"  rendered {src.name}", file=sys.stderr)
        else:
            print(f"  cached  {src.name}", file=sys.stderr)

        meta = metadata.get(src.name, {})
        name = src.name
        title = meta.get("title", "")
        domain = meta.get("domain", "")
        level = (meta.get("level") or "").upper() or "L?"
        family = meta.get("family", "")
        aliases = " ".join(meta.get("aliases", []) if isinstance(meta.get("aliases"), list) else [])
        tags = " ".join(meta.get("tags", []) if isinstance(meta.get("tags"), list) else [])

        blob = " ".join([name, title, domain, family, aliases, tags]).lower()
        # link the user back to the template file so they can open it directly
        rel_drawio = Path("..") / "plugins" / "sap-architecture" / "skills" / "sap-architecture" / "assets" / "reference-examples" / src.name
        cards.append(CARD_TEMPLATE.format(
            blob=html.escape(blob),
            drawio_link=html.escape(str(rel_drawio)),
            thumb=html.escape(thumb.name),
            name=html.escape(name),
            title=html.escape(title) if title else "",
            domain=html.escape(domain) if domain else "—",
            level=html.escape(level),
        ))

    if not args.thumbs_only:
        index = out_dir / "index.html"
        index.write_text(
            HTML_TEMPLATE.format(count=len(templates), cards="\n".join(cards)),
            encoding="utf-8",
        )
        print(f"\ngallery: {index}", file=sys.stderr)

    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
