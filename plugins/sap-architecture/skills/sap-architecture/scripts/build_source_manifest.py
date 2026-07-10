#!/usr/bin/env python3
"""Build a deterministic provenance manifest for bundled SAP assets."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Iterable


SKILL_DIR = Path(__file__).resolve().parents[1]
REFERENCE_DIR = SKILL_DIR / "assets" / "reference-examples"
LIBRARY_DIR = SKILL_DIR / "assets" / "libraries"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def source_group(name: str) -> str:
    if name.startswith("btp_"):
        return "SAP/btp-solution-diagrams"
    if name.startswith("ac_"):
        return "SAP/architecture-center"
    if name.startswith("ext_"):
        return "SAP/sap-btp-reference-architectures"
    return "local-metadata"


def main(argv: Iterable[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=SKILL_DIR / "assets" / "source-manifest.json")
    ap.add_argument("--generated-at", required=True, help="ISO date used for deterministic regeneration")
    ap.add_argument("--fork-commit", required=True)
    args = ap.parse_args(list(argv) if argv is not None else None)

    references = [
        {
            "file": path.name,
            "source_group": source_group(path.name),
            "sha256": sha256(path),
        }
        for path in sorted(REFERENCE_DIR.glob("*.drawio"))
    ]
    libraries = [
        {"file": path.name, "sha256": sha256(path)}
        for path in sorted(LIBRARY_DIR.glob("*.xml"))
    ]
    counts: dict[str, int] = {}
    for item in references:
        counts[item["source_group"]] = counts.get(item["source_group"], 0) + 1
    payload = {
        "schema_version": 1,
        "generated_at": args.generated_at,
        "fork_upstream": "https://github.com/marianfoo/btp-drawio-skill",
        "fork_upstream_commit": args.fork_commit,
        "source_revision_status": (
            "Bundled-file hashes are authoritative. Exact SAP upstream commits were not recorded by the source package; "
            "do not infer them from current repository HEADs."
        ),
        "reference_count": len(references),
        "reference_counts_by_source": counts,
        "library_count": len(libraries),
        "references": references,
        "libraries": libraries,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
