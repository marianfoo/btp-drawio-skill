#!/usr/bin/env python3
"""Score one .drawio candidate against a corpus of SAP reference diagrams.

Use this after generating a diagram. The best match should usually be the
template you started from. If no reference scores high, the diagram probably
drifted away from SAP Architecture Center structure.

Usage:
  score_corpus.py my-diagram.drawio
  score_corpus.py --top 10 --min-score 90 my-diagram.drawio
  score_corpus.py --references /path/to/SAP/architecture-center my-diagram.drawio
  score_corpus.py --min-sap-like 90 semantic-diagram.drawio
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

from compare import compare, fingerprint, sap_likeness
from validate import validate


@dataclass
class RankedScore:
    reference: str
    score: float
    breakdown: dict[str, float]
    diffs: list[str]


def default_reference_dir() -> Path:
    return Path(__file__).resolve().parents[1] / "assets" / "reference-examples"


def collect_references(paths: list[Path]) -> list[Path]:
    refs: list[Path] = []
    for p in paths:
        if p.is_dir():
            refs.extend(sorted(p.rglob("*.drawio")))
        elif p.suffix.lower() == ".drawio":
            refs.append(p)
    return refs


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("candidate", type=Path)
    ap.add_argument(
        "--references",
        type=Path,
        action="append",
        default=None,
        help="reference .drawio file or directory; can be passed multiple times",
    )
    ap.add_argument("--top", type=int, default=5)
    ap.add_argument("--min-score", type=float, default=None, help="exit 1 if best score is below this value")
    ap.add_argument("--min-sap-like", type=float, default=None, help="exit 1 if reference-free SAP-likeness is below this value")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--score", action="store_true", help="print only the best score")
    ap.add_argument("--sap-score", action="store_true", help="print only the reference-free SAP-likeness score")
    args = ap.parse_args()

    if not args.candidate.exists():
        print(f"{args.candidate}: candidate not found", file=sys.stderr)
        return 2

    reference_inputs = args.references or [default_reference_dir()]
    refs = collect_references(reference_inputs)
    if not refs:
        print("no reference .drawio files found", file=sys.stderr)
        return 2

    candidate_fp = fingerprint(args.candidate)
    validation_report = validate(args.candidate)
    quality = sap_likeness(candidate_fp, validator_errors=len(validation_report.errors))
    ranked: list[RankedScore] = []
    for ref in refs:
        result = compare(fingerprint(ref), candidate_fp)
        ranked.append(RankedScore(str(ref), result.score, result.breakdown, result.diffs))
    ranked.sort(key=lambda r: (-r.score, r.reference))
    top = ranked[: args.top]
    best = top[0].score if top else 0.0

    if args.score:
        print(f"{best:.1f}")
    elif args.sap_score:
        print(f"{quality.score:.1f}")
    elif args.json:
        print(json.dumps({"sap_likeness": asdict(quality), "ranked": [asdict(r) for r in top]}, indent=2))
    else:
        print(f"candidate : {args.candidate}")
        print(f"references: {len(refs)}")
        print(f"best      : {best:.1f}/100 corpus similarity")
        print(f"sap-like  : {quality.score:.1f}/100 reference-free quality")
        if quality.issues:
            print(f"sap issues: {quality.issues[0]}")
        for i, item in enumerate(top, 1):
            print(f"{i}. {item.score:5.1f}  {item.reference}")
            if item.diffs:
                print(f"   - {item.diffs[0]}")

    if args.min_score is not None and best < args.min_score:
        return 1
    if args.min_sap_like is not None and quality.score < args.min_sap_like:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
