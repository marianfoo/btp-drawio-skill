#!/usr/bin/env python3
"""Run the guarded final gate for a template-derived SAP draw.io diagram."""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import xml.etree.ElementTree as ET
from dataclasses import asdict
from pathlib import Path
from typing import Any, Iterable

THIS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(THIS_DIR))

import compare  # type: ignore[import-not-found]  # noqa: E402
import provenance  # type: ignore[import-not-found]  # noqa: E402
import render  # type: ignore[import-not-found]  # noqa: E402
import validate  # type: ignore[import-not-found]  # noqa: E402
import validate_semantics  # type: ignore[import-not-found]  # noqa: E402


REQUIRED_VISUAL_CHECKS = {
    "nonblank",
    "legible",
    "no_incoherent_overlap",
    "flows_traceable",
    "provenance_visible",
    "sap_style_consistent",
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def issue_signature(issue: Any) -> tuple[str, str, str]:
    return (issue.category, issue.msg, issue.cell or "")


def load_visual_review(path: Path, candidate_png: Path, reference_png: Path) -> list[str]:
    errors: list[str] = []
    try:
        review = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return [f"visual review could not be read: {exc}"]
    if review.get("schema_version") != 1:
        errors.append("visual review requires schema_version 1")
    if review.get("verdict") != "pass":
        errors.append("visual review verdict is not pass")
    checks = review.get("checks", {})
    if (
        not isinstance(checks, dict)
        or not REQUIRED_VISUAL_CHECKS <= set(checks)
        or not all(checks.get(name) is True for name in REQUIRED_VISUAL_CHECKS)
    ):
        errors.append("visual review checks are incomplete")
    if review.get("candidate_sha256") != sha256(candidate_png):
        errors.append("candidate PNG changed after visual review")
    if review.get("reference_sha256") != sha256(reference_png):
        errors.append("reference PNG changed after visual review")
    if not str(review.get("reviewer", "")).strip() or not str(review.get("notes", "")).strip():
        errors.append("visual review requires reviewer and notes")
    return errors


def write_report(path: Path, report: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")


def main(argv: Iterable[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("drawio", type=Path)
    ap.add_argument("spec", type=Path)
    ap.add_argument("--target", type=Path, required=True, help="the exact template selected during scaffold")
    ap.add_argument("--out-dir", type=Path, required=True)
    ap.add_argument("--min-score", type=float, default=90.0)
    ap.add_argument("--mode", choices=("template", "semantic-fallback"), default="template")
    ap.add_argument("--visual-review", type=Path)
    ap.add_argument("--report", type=Path)
    args = ap.parse_args(list(argv) if argv is not None else None)
    missing = [path for path in (args.drawio, args.spec, args.target) if not path.exists()]
    if missing:
        print(f"missing input: {', '.join(map(str, missing))}", file=sys.stderr)
        return 2

    args.out_dir.mkdir(parents=True, exist_ok=True)
    report_path = args.report or args.out_dir / "gate-report.json"
    result: dict[str, Any] = {
        "schema_version": 1,
        "status": "failed",
        "candidate": str(args.drawio.resolve()),
        "target": str(args.target.resolve()),
        "spec": str(args.spec.resolve()),
        "mode": args.mode,
        "errors": [],
        "warnings": [],
    }
    errors: list[str] = result["errors"]
    warnings: list[str] = result["warnings"]

    try:
        spec = validate_semantics.load_spec(args.spec)
        semantic_report = validate_semantics.validate_semantics(args.drawio, args.spec)
        result["semantics"] = asdict(semantic_report)
        errors.extend(issue.message for issue in semantic_report.errors)

        provenance_spec = spec.get("provenance", {})
        if not isinstance(provenance_spec, dict):
            raise ValueError("spec provenance must be an object")
        allowed_values = provenance_spec.get("allowed_raster_hashes", [])
        if not isinstance(allowed_values, list) or not all(isinstance(value, str) for value in allowed_values):
            raise ValueError("provenance.allowed_raster_hashes must be a string list")
        allowed_hashes = set(allowed_values)
        provenance_report = provenance.audit_tree(
            ET.parse(args.drawio).getroot(),
            allowed_raster_hashes=allowed_hashes,
        )
        result["provenance"] = asdict(provenance_report)
        errors.extend(issue.message for issue in provenance_report.errors)
        errors.extend(issue.message for issue in provenance_report.warnings)

        candidate_validation = validate.validate(args.drawio)
        target_validation = validate.validate(args.target)
        inherited_warnings = {issue_signature(issue) for issue in target_validation.warnings}
        if args.mode == "template":
            new_warnings = [issue for issue in candidate_validation.warnings if issue_signature(issue) not in inherited_warnings]
        else:
            new_warnings = candidate_validation.warnings
        result["structural"] = {
            "candidate": candidate_validation.to_json(),
            "target_warning_count": len(target_validation.warnings),
            "new_warnings": [asdict(issue) for issue in new_warnings],
        }
        errors.extend(issue.msg for issue in candidate_validation.errors)
        errors.extend(f"new structural warning: {issue.msg}" for issue in new_warnings)
        if target_validation.errors:
            warnings.append(f"selected SAP template has {len(target_validation.errors)} validator error(s); review upstream fixture")

        comparison = compare.compare(compare.fingerprint(args.target), compare.fingerprint(args.drawio))
        result["pinned_template"] = {
            "score": comparison.score,
            "minimum": args.min_score,
            "breakdown": comparison.breakdown,
            "diffs": comparison.diffs,
        }
        if args.mode == "template" and comparison.score < args.min_score:
            errors.append(f"pinned-template score {comparison.score:.1f} is below {args.min_score:.1f}")
        quality = compare.sap_likeness(
            compare.fingerprint(args.drawio),
            validator_errors=len(candidate_validation.errors),
        )
        result["sap_likeness"] = asdict(quality)
        if args.mode == "semantic-fallback" and quality.score < args.min_score:
            errors.append(f"SAP-likeness score {quality.score:.1f} is below {args.min_score:.1f}")
    except (ET.ParseError, OSError, ValueError, json.JSONDecodeError) as exc:
        errors.append(f"gate input failed: {exc}")

    candidate_png = args.out_dir / "candidate.png"
    reference_png = args.out_dir / "reference.png"
    drawio_cli = render.find_drawio_cli()
    if not drawio_cli:
        errors.append("draw.io CLI unavailable; rendered visual verification is mandatory")
    else:
        candidate_rc = render.render_one(drawio_cli, args.drawio, candidate_png, "png", 1.5, 10, False, False)
        reference_rc = render.render_one(drawio_cli, args.target, reference_png, "png", 1.5, 10, False, False)
        if candidate_rc or reference_rc or not candidate_png.exists() or not reference_png.exists():
            errors.append("candidate/reference rendering failed")
        else:
            result["renders"] = {
                "candidate": str(candidate_png.resolve()),
                "candidate_sha256": sha256(candidate_png),
                "reference": str(reference_png.resolve()),
                "reference_sha256": sha256(reference_png),
            }

    if not errors and not args.visual_review:
        result["status"] = "awaiting-visual-review"
        result["errors"].append("hash-bound visual review is required")
    elif not errors and args.visual_review:
        if not args.visual_review.exists():
            errors.append("visual review file not found")
        else:
            errors.extend(load_visual_review(args.visual_review, candidate_png, reference_png))

    if not errors:
        result["status"] = "pass"
    write_report(report_path, result)
    print(f"guarded delivery gate: {result['status']}")
    print(f"report: {report_path}")
    if result.get("renders"):
        print(f"candidate render: {candidate_png}")
        print(f"reference render: {reference_png}")
    for error in errors:
        print(f"ERROR: {error}")
    return 0 if result["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
