#!/usr/bin/env python3
"""Record a hash-bound visual review for rendered candidate/reference images."""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable


REQUIRED_CHECKS = (
    "nonblank",
    "legible",
    "no_incoherent_overlap",
    "flows_traceable",
    "provenance_visible",
    "sap_style_consistent",
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main(argv: Iterable[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("candidate_png", type=Path)
    ap.add_argument("reference_png", type=Path)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--reviewer", required=True)
    ap.add_argument("--verdict", choices=("pass", "fail"), required=True)
    ap.add_argument("--notes", required=True)
    ap.add_argument("--check", action="append", default=[], choices=REQUIRED_CHECKS)
    args = ap.parse_args(list(argv) if argv is not None else None)
    if not args.candidate_png.exists() or not args.reference_png.exists():
        print("candidate and reference PNG files must exist", file=sys.stderr)
        return 2
    checks = {name: name in set(args.check) for name in REQUIRED_CHECKS}
    if args.verdict == "pass" and not all(checks.values()):
        missing = [name for name, passed in checks.items() if not passed]
        print(f"pass verdict requires all checks: missing {', '.join(missing)}", file=sys.stderr)
        return 2
    payload = {
        "schema_version": 1,
        "reviewed_at": datetime.now(timezone.utc).isoformat(),
        "reviewer": args.reviewer,
        "verdict": args.verdict,
        "notes": args.notes,
        "candidate_png": str(args.candidate_png.resolve()),
        "candidate_sha256": sha256(args.candidate_png),
        "reference_png": str(args.reference_png.resolve()),
        "reference_sha256": sha256(args.reference_png),
        "checks": checks,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
