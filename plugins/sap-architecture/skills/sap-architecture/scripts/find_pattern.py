#!/usr/bin/env python3
"""Search the bundled SAP template registry for templates that match a design pattern.

This is the "if SAP did something similar, find it for me" tool. Use cases
the LLM should reach for it:

  - "I need to draw 4 zones with a vertical network divider — what SAP
     template has that already?"
  - "Which templates use exactly TRUST + Authenticate + A2A + MCP pills?"
  - "Show me templates with ≥ 6 BTP service icons inside a Cloud Solutions
     band, so I can match the spacing/sizing they use."
  - "Which templates have Joule as a separate purple zone (not nested in BTP)?"

The script reads the precomputed `assets/reference-examples/template-profiles.json`
(built by `profile_template.py --build-registry`) and ranks templates by how
well their structural profile matches the query.

Usage:
  find_pattern.py "vertical network divider"
  find_pattern.py "joule purple zone"
  find_pattern.py --pill TRUST --pill A2A --pill MCP
  find_pattern.py --zones 4 --icons-min 8
  find_pattern.py --pattern tri-zone-joule-btp-third-party
  find_pattern.py --top 5 --json "identity flow at bottom"

Output: ranked templates with the matching evidence per template.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

THIS_DIR = Path(__file__).resolve().parent
REGISTRY_DEFAULT = THIS_DIR.parent / "assets" / "reference-examples" / "template-profiles.json"


@dataclass
class Match:
    name: str
    score: float
    reasons: list[str] = field(default_factory=list)
    profile: dict = field(default_factory=dict)


def load_registry(path: Path) -> dict:
    if not path.exists():
        print(
            f"registry not found: {path}\n"
            "Run: python3 .../scripts/profile_template.py --build-registry",
            file=sys.stderr,
        )
        sys.exit(2)
    return json.loads(path.read_text(encoding="utf-8"))


def textual_score(profile: dict, terms: set[str]) -> tuple[float, list[str]]:
    """Score how often the search terms appear in the profile's textual fields."""
    haystack_parts = [
        profile.get("title", ""),
        profile.get("description", ""),
        " ".join(profile.get("aliases") or []),
        " ".join(profile.get("tags") or []),
        " ".join(profile.get("detected_patterns") or []),
        " ".join(p.get("label", "") for p in (profile.get("zones") or [])),
        " ".join(p.get("label", "") for p in (profile.get("cards") or [])),
        " ".join(profile.get("pill_vocab") or []),
    ]
    haystack = " ".join(str(s) for s in haystack_parts).lower()
    hits = []
    score = 0.0
    for t in terms:
        n = haystack.count(t)
        if n > 0:
            hits.append(f"{t}×{n}")
            score += n
    return score, hits


def pattern_match(profile: dict, want_patterns: list[str]) -> tuple[float, list[str]]:
    have = set(profile.get("detected_patterns") or [])
    matched = [p for p in want_patterns if p in have]
    return (len(matched) * 8.0, matched)


def pill_match(profile: dict, want_pills: list[str]) -> tuple[float, list[str]]:
    have = set(p.lower() for p in (profile.get("pill_vocab") or []))
    matched = [p for p in want_pills if p.lower() in have]
    return (len(matched) * 5.0, matched)


def structure_match(profile: dict, want: dict) -> tuple[float, list[str]]:
    """Partial-credit scoring for desired counts (zones, cards, icons, pills, edges)."""
    structure = profile.get("structure_summary", {})
    score = 0.0
    reasons = []
    pairs = {
        "zones": "top_level_zones",
        "nested_zones": "nested_zones",
        "cards": "cards",
        "icons": "icons",
        "pills": "pills",
        "edges": "edges",
    }
    for key, prof_key in pairs.items():
        if want.get(key) is not None:
            target = int(want[key])
            actual = int(structure.get(prof_key, 0))
            # Award full points when exact, partial when within 20%
            if actual == target:
                score += 6.0
                reasons.append(f"{key}={actual}")
            elif abs(actual - target) <= max(2, target * 0.2):
                score += 3.0
                reasons.append(f"{key}={actual}~={target}")
        if want.get(f"{key}_min") is not None:
            target = int(want[f"{key}_min"])
            actual = int(structure.get(prof_key, 0))
            if actual >= target:
                score += 2.0
                reasons.append(f"{key}>={actual}")
    return score, reasons


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("query", nargs="*", help="free-text search across titles, tags, patterns, labels")
    ap.add_argument("--registry", type=Path, default=REGISTRY_DEFAULT)
    ap.add_argument("--top", type=int, default=5)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--pattern", action="append", default=[],
                    help="require a specific detected_patterns tag (repeatable)")
    ap.add_argument("--pill", action="append", default=[],
                    help="require a specific pill verb in vocab (repeatable)")
    ap.add_argument("--zones", type=int, help="prefer templates with this many top-level zones")
    ap.add_argument("--zones-min", type=int)
    ap.add_argument("--cards", type=int)
    ap.add_argument("--cards-min", type=int)
    ap.add_argument("--icons", type=int)
    ap.add_argument("--icons-min", type=int)
    ap.add_argument("--pills", type=int)
    ap.add_argument("--pills-min", type=int)
    ap.add_argument("--edges", type=int)
    ap.add_argument("--edges-min", type=int)
    ap.add_argument("--family", help="restrict to a specific family tag (e.g. ra0029, btp, ext-mdi)")
    ap.add_argument("--list-patterns", action="store_true",
                    help="print every detected_patterns tag observed in the registry")
    ap.add_argument("--list-pills", action="store_true",
                    help="print every pill verb observed across the registry")
    args = ap.parse_args()

    reg = load_registry(args.registry)
    profiles = reg.get("templates", {})

    if args.list_patterns:
        all_pats: dict[str, int] = {}
        for prof in profiles.values():
            for p in (prof.get("detected_patterns") or []):
                all_pats[p] = all_pats.get(p, 0) + 1
        for pat, n in sorted(all_pats.items(), key=lambda kv: -kv[1]):
            print(f"  {n:>3}× {pat}")
        return 0

    if args.list_pills:
        all_pills: dict[str, int] = {}
        for prof in profiles.values():
            for p in (prof.get("pill_vocab") or []):
                all_pills[p] = all_pills.get(p, 0) + 1
        for pill, n in sorted(all_pills.items(), key=lambda kv: -kv[1]):
            print(f"  {n:>3}× {pill!r}")
        return 0

    free_text = " ".join(args.query).lower().strip()
    terms = set(re.findall(r"[a-z0-9]+", free_text)) if free_text else set()

    want_structure = {
        "zones": args.zones, "zones_min": args.zones_min,
        "cards": args.cards, "cards_min": args.cards_min,
        "icons": args.icons, "icons_min": args.icons_min,
        "pills": args.pills, "pills_min": args.pills_min,
        "edges": args.edges, "edges_min": args.edges_min,
    }

    matches: list[Match] = []
    for name, profile in profiles.items():
        if args.family and profile.get("family") != args.family:
            continue
        score = 0.0
        reasons: list[str] = []

        if terms:
            s, hits = textual_score(profile, terms)
            if s > 0:
                score += s
                reasons.append("text: " + ", ".join(hits[:8]))

        if args.pattern:
            s, hits = pattern_match(profile, args.pattern)
            if s > 0:
                score += s
                reasons.append("pattern: " + ", ".join(hits))
            else:
                # Required patterns not found — skip this template
                continue

        if args.pill:
            s, hits = pill_match(profile, args.pill)
            if s > 0:
                score += s
                reasons.append("pills: " + ", ".join(hits))

        s, hits = structure_match(profile, want_structure)
        if s > 0:
            score += s
            reasons.append("structure: " + ", ".join(hits))

        # Light prior: prefer primary templates when scores are tied
        if profile.get("primary"):
            score += 0.5
            reasons.append("(primary)")

        if score > 0 or not (terms or args.pattern or args.pill or any(want_structure.values())):
            matches.append(Match(name=name, score=score, reasons=reasons, profile=profile))

    matches.sort(key=lambda m: (-m.score, m.name))
    matches = matches[: args.top]

    if args.json:
        out = [{
            "name": m.name,
            "score": round(m.score, 1),
            "reasons": m.reasons,
            "title": m.profile.get("title", ""),
            "description": m.profile.get("description", ""),
            "structure": m.profile.get("structure_summary", {}),
            "detected_patterns": m.profile.get("detected_patterns", []),
            "pill_vocab": m.profile.get("pill_vocab", []),
        } for m in matches]
        print(json.dumps(out, indent=2))
        return 0

    if not matches:
        print("no templates matched the criteria")
        return 0

    for i, m in enumerate(matches, 1):
        print(f"{i}. {m.score:5.1f}  {m.name}")
        if m.profile.get("title"):
            print(f"     title    : {m.profile['title']}")
        if m.profile.get("structure_summary"):
            print(f"     structure: {m.profile['structure_summary']}")
        if m.profile.get("detected_patterns"):
            print(f"     patterns : {', '.join(m.profile['detected_patterns'][:8])}")
        if m.profile.get("pill_vocab"):
            print(f"     pills    : {', '.join(repr(p) for p in m.profile['pill_vocab'][:6])}")
        for r in m.reasons:
            print(f"     • {r}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
