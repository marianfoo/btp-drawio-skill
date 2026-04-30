#!/usr/bin/env python3
"""Scaffold a new SAP architecture diagram by copying the closest reference template.

This script enforces the single most important rule of the skill: never draw
from scratch — always start from a pristine SAP reference template.

It combines `select_reference.py` (rank candidates) with a copy step:

  1. Rank bundled templates against the request text.
  2. Pick the top match (or honor an explicit --template path).
  3. Copy it to the destination, preserving canvas, zones, palette, fonts.
  4. Optionally rename the diagram name and the title-band text.

After scaffolding, the LLM should make minimal label edits to fit the request,
then run autofix.py / validate.py / compare.py.

Usage:
  scaffold_diagram.py "MCP client calling BTP via Cloud Connector" --out docs/diagram.drawio
  scaffold_diagram.py "Agentic AI on BTP with Joule" --out docs/agentic-ai.drawio
  scaffold_diagram.py --template ac_RA0029_AgenticAI_root.drawio --out docs/foo.drawio "..."
  scaffold_diagram.py --top 5 --dry-run "Agentic AI on BTP"

Exit code:
  0 — file scaffolded (or --dry-run printed candidates)
  1 — error
  2 — usage
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

THIS_DIR = Path(__file__).resolve().parent
SCRIPTS_DIR = THIS_DIR
ASSETS_DIR = THIS_DIR.parent / "assets" / "reference-examples"

sys.path.insert(0, str(SCRIPTS_DIR))
import select_reference  # type: ignore[import-not-found]


def rank_candidates(query: str, top: int) -> list[select_reference.Candidate]:
    refs = sorted(ASSETS_DIR.rglob("*.drawio"))
    return sorted(
        (select_reference.score(p, query) for p in refs),
        key=lambda c: (-c.score, c.path),
    )[:top]


def rename_diagram(path: Path, new_name: str) -> bool:
    """Update the first <diagram name="..."> attribute. Returns True on change."""
    text = path.read_text(encoding="utf-8")
    try:
        root = ET.fromstring(text)
    except ET.ParseError:
        return False
    diagram = root.find(".//diagram")
    if diagram is None:
        return False
    diagram.set("name", new_name)
    ET.register_namespace("", "")
    path.write_text(ET.tostring(root, encoding="unicode"), encoding="utf-8")
    return True


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("description", nargs="*", help="diagram request; stdin if omitted")
    ap.add_argument(
        "-o", "--out",
        dest="destination",
        type=Path,
        help="path to the scaffolded .drawio file (omit with --dry-run)",
    )
    ap.add_argument("--template", help="explicit template filename (e.g. ac_RA0029_AgenticAI_root.drawio)")
    ap.add_argument("--top", type=int, default=5, help="show this many ranked candidates")
    ap.add_argument("--dry-run", action="store_true", help="don't copy; just print top candidates")
    ap.add_argument("--diagram-name", help="rename the <diagram name=...> attribute after copy")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--force", action="store_true", help="overwrite destination if it exists")
    args = ap.parse_args()

    query = " ".join(args.description).strip() or sys.stdin.read().strip()
    if not query and not args.template:
        print("description or --template required", file=sys.stderr)
        return 2

    if not ASSETS_DIR.exists():
        print(f"{ASSETS_DIR}: reference directory not found", file=sys.stderr)
        return 1

    chosen: Path | None = None
    candidates: list[select_reference.Candidate] = []

    if args.template:
        candidate_path = (ASSETS_DIR / args.template).resolve()
        if not candidate_path.exists():
            # Fallback: case-insensitive match by stem or filename
            target = args.template.lower()
            for p in ASSETS_DIR.rglob("*.drawio"):
                if p.name.lower() == target or p.stem.lower() == target.removesuffix(".drawio"):
                    candidate_path = p
                    break
        if not candidate_path.exists():
            print(f"--template {args.template!r}: not found in {ASSETS_DIR}", file=sys.stderr)
            return 1
        chosen = candidate_path
    else:
        candidates = rank_candidates(query, args.top)
        if not candidates:
            print("no candidates found", file=sys.stderr)
            return 1
        chosen = Path(candidates[0].path)

    if args.dry_run or args.destination is None:
        if args.json:
            payload = {
                "query": query,
                "chosen": str(chosen) if chosen else None,
                "candidates": [
                    {"path": c.path, "score": c.score, "reasons": c.reasons[:3]}
                    for c in candidates
                ],
            }
            print(json.dumps(payload, indent=2))
        else:
            print(f"query  : {query}")
            print(f"chosen : {chosen}")
            if candidates:
                print(f"top {len(candidates)} candidates:")
                for i, c in enumerate(candidates, 1):
                    print(f"  {i}. {c.score:5.1f}  {Path(c.path).name}")
                    for reason in c.reasons[:2]:
                        print(f"     - {reason}")
        return 0

    if chosen is None:
        print("no template chosen", file=sys.stderr)
        return 1
    dest = args.destination.resolve()
    if dest.exists() and not args.force:
        print(f"{dest}: already exists (use --force to overwrite)", file=sys.stderr)
        return 1
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(chosen, dest)

    renamed = False
    if args.diagram_name:
        renamed = rename_diagram(dest, args.diagram_name)

    if args.json:
        payload = {
            "query": query,
            "template": str(chosen),
            "destination": str(dest),
            "renamed_diagram": bool(renamed),
            "candidates": [
                {"path": c.path, "score": c.score, "reasons": c.reasons[:3]}
                for c in candidates
            ],
        }
        print(json.dumps(payload, indent=2))
    else:
        print(f"scaffolded {dest} from {chosen.name}")
        if args.diagram_name and not renamed:
            print(f"warning: --diagram-name {args.diagram_name!r} did not match a <diagram> element")
        if candidates:
            print()
            print("alternative templates (open one if the chosen one is the wrong family):")
            for i, c in enumerate(candidates[: args.top], 1):
                print(f"  {i}. {c.score:5.1f}  {Path(c.path).name}")
        print()
        print("Next steps:")
        print(f"  1. Edit {dest.name} surgically — change labels, swap services, keep canvas/zones/palette")
        print(f"  2. python3 {SCRIPTS_DIR}/autofix.py --write {dest}")
        print(f"  3. python3 {SCRIPTS_DIR}/validate.py {dest}")
        print(f"  4. python3 {SCRIPTS_DIR}/compare.py {chosen} {dest}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
