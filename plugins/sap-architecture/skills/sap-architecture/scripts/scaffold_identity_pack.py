#!/usr/bin/env python3
"""Compose a guarded multi-page SAP identity pack from pinned SAP templates.

The script never generates mxGraph geometry. It copies one complete page from
each configured template, applies exact-label variations, records page-level
source metadata, and writes a schema-v2 semantic contract plus target manifest.
"""
from __future__ import annotations

import argparse
import copy
import csv
import hashlib
import json
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Iterable

THIS_DIR = Path(__file__).resolve().parent
SKILL_DIR = THIS_DIR.parent
REFERENCE_DIR = SKILL_DIR / "assets" / "reference-examples"
DEFAULT_PATTERN = SKILL_DIR / "assets" / "patterns" / "identity-architecture-pack.json"
sys.path.insert(0, str(THIS_DIR))

import provenance  # type: ignore[import-not-found]  # noqa: E402
import relabel  # type: ignore[import-not-found]  # noqa: E402
import validate_semantics  # type: ignore[import-not-found]  # noqa: E402


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_pattern(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or data.get("schema_version") != 1:
        raise ValueError("identity pack pattern requires schema_version 1")
    pages = data.get("pages")
    if not isinstance(pages, list) or not pages:
        raise ValueError("identity pack pattern requires pages")
    return data


def load_variations(path: Path | None) -> list[dict[str, str]]:
    if path is None:
        return []
    with path.open(newline="", encoding="utf-8-sig") as handle:
        rows = list(csv.DictReader(handle))
    required = {"page", "match", "replacement", "claim_state"}
    if rows and not required <= set(rows[0]):
        raise ValueError(f"variation CSV requires columns: {', '.join(sorted(required))}")
    result: list[dict[str, str]] = []
    for index, raw in enumerate(rows, start=2):
        row = {str(key): str(value or "").strip() for key, value in raw.items() if key is not None}
        if not all(row.get(key) for key in required):
            raise ValueError(f"variation CSV row {index} has blank required fields")
        if row["claim_state"] not in validate_semantics.CLAIM_STATES:
            raise ValueError(f"variation CSV row {index} has invalid claim_state: {row['claim_state']}")
        result.append(row)
    return result


def variation_claim(row: dict[str, str], index: int) -> dict[str, str]:
    claim: dict[str, str] = {
        "id": row.get("claim_id") or f"variation-{index:03d}",
        "state": row["claim_state"],
        "text": row.get("claim_text") or f"{row['page']}: {row['replacement']}",
    }
    for key in (
        "source_url",
        "checked_on",
        "decision_status",
        "evidence",
        "confirmation_needed",
        "protocol",
        "scope",
    ):
        if row.get(key):
            claim[key] = row[key]
    return claim


def apply_exact_relabel(diagram: ET.Element, match: str, replacement: str, *, context: str) -> None:
    replacements = relabel.relabel_tree(diagram, {}, {relabel.clean_label(match): replacement})
    if len(replacements) != 1:
        raise ValueError(f"{context}: expected one exact label match for {match!r}, found {len(replacements)}")


def compose(
    pattern: dict[str, Any],
    variations: list[dict[str, str]],
    *,
    output: Path,
    spec_output: Path,
    targets_output: Path,
) -> tuple[Path, Path, Path]:
    page_names = [str(page.get("name", "")) for page in pattern["pages"]]
    if len(page_names) != len(set(page_names)) or any(not name for name in page_names):
        raise ValueError("pattern page names must be unique and non-empty")
    unknown_pages = sorted({row["page"] for row in variations} - set(page_names))
    if unknown_pages:
        raise ValueError(f"variation CSV references unknown pages: {', '.join(unknown_pages)}")

    first_template = REFERENCE_DIR / str(pattern["pages"][0]["template"])
    first_root = ET.parse(first_template).getroot()
    if first_root.tag != "mxfile":
        raise ValueError(f"template is not an mxfile: {first_template}")
    pack_root = copy.deepcopy(first_root)
    for diagram in list(pack_root.findall("diagram")):
        pack_root.remove(diagram)
    pack_root.set("data-pack-pattern", str(pattern.get("pattern", "sap-identity-architecture-pack")))
    pack_root.set("data-canonical-source", "true")

    targets: list[dict[str, Any]] = []
    spec_pages: list[dict[str, Any]] = []
    for page_index, page in enumerate(pattern["pages"], start=1):
        if not isinstance(page, dict):
            raise ValueError(f"pattern page {page_index} must be an object")
        template = REFERENCE_DIR / str(page.get("template", ""))
        if not template.exists():
            raise ValueError(f"missing template: {template}")
        source_root = ET.parse(template).getroot()
        source_diagram = source_root.find("diagram") if source_root.tag == "mxfile" else None
        if source_diagram is None or source_diagram.find("mxGraphModel") is None:
            raise ValueError(f"template has no uncompressed diagram page: {template}")
        diagram = copy.deepcopy(source_diagram)
        page_name = str(page["name"])
        source_url = str(page.get("source_url", ""))
        if not source_url.startswith("https://"):
            raise ValueError(f"page {page_name} requires an HTTPS source_url")
        diagram.set("id", f"identity-pack-page-{page_index:02d}")
        diagram.set("name", page_name)
        diagram.set("data-guarded-source-template", template.name)
        diagram.set("data-guarded-source-url", source_url)
        for relabel_item in page.get("relabels", []):
            if not isinstance(relabel_item, dict):
                raise ValueError(f"page {page_name} relabels must be objects")
            apply_exact_relabel(
                diagram,
                str(relabel_item.get("match", "")),
                str(relabel_item.get("replacement", "")),
                context=f"page {page_name}",
            )
        for row in (item for item in variations if item["page"] == page_name):
            apply_exact_relabel(diagram, row["match"], row["replacement"], context=f"variation page {page_name}")
        pack_root.append(diagram)
        targets.append(
            {
                "page_index": page_index,
                "page_name": page_name,
                "template": str(template.resolve()),
                "template_sha256": sha256(template),
                "source_url": source_url,
            }
        )
        spec_pages.append(
            {
                key: copy.deepcopy(value)
                for key, value in page.items()
                if key
                in {
                    "name",
                    "purpose",
                    "level",
                    "required_nodes",
                    "required_zones",
                    "required_terms",
                    "required_flows",
                    "forbidden_terms",
                }
            }
        )

    provenance.sanitize_tree(
        pack_root,
        source_template="SAP identity reference family (page-specific sources recorded)",
        source_url=str(pattern.get("source_family_url", "")),
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    tree = ET.ElementTree(pack_root)
    ET.indent(tree, space="  ")
    tree.write(output, encoding="unicode", xml_declaration=False)

    claims = copy.deepcopy(pattern.get("claims", []))
    claims.extend(variation_claim(row, index) for index, row in enumerate(variations, start=1))
    claim_probe = validate_semantics.SemanticReport()
    validate_semantics.validate_claims({"claims": claims}, claim_probe)
    if claim_probe.errors:
        raise ValueError("; ".join(issue.message for issue in claim_probe.errors))
    spec = {
        "schema_version": 2,
        "subject": str(pattern.get("title", "SAP Identity Architecture Pack")),
        "status": str(pattern.get("status", "internal-draft")),
        "canonical_drawio": str(output.resolve()),
        "claims": claims,
        "pages": spec_pages,
        "provenance": {"allowed_raster_hashes": []},
        "currentness": {
            "control_file": str((SKILL_DIR / "assets" / "currentness.json").resolve()),
            "required_claim_ids": ["btp-cf-saml-user-interactive", "iag-ias-api-v1-user-group-sync"],
        },
    }
    spec_output.parent.mkdir(parents=True, exist_ok=True)
    spec_output.write_text(json.dumps(spec, indent=2) + "\n", encoding="utf-8")
    targets_payload = {
        "schema_version": 1,
        "canonical_drawio": str(output.resolve()),
        "pattern": str(pattern.get("pattern", "")),
        "pages": targets,
    }
    targets_output.parent.mkdir(parents=True, exist_ok=True)
    targets_output.write_text(json.dumps(targets_payload, indent=2) + "\n", encoding="utf-8")
    return output, spec_output, targets_output


def main(argv: Iterable[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pattern", type=Path, default=DEFAULT_PATTERN)
    ap.add_argument("--variation-csv", type=Path)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--spec-out", type=Path)
    ap.add_argument("--targets-out", type=Path)
    args = ap.parse_args(list(argv) if argv is not None else None)
    if not args.pattern.exists() or (args.variation_csv and not args.variation_csv.exists()):
        print("pattern and variation CSV inputs must exist", file=sys.stderr)
        return 2
    spec_output = args.spec_out or args.out.with_suffix(".spec.json")
    targets_output = args.targets_out or args.out.with_suffix(".targets.json")
    try:
        outputs = compose(
            load_pattern(args.pattern),
            load_variations(args.variation_csv),
            output=args.out,
            spec_output=spec_output,
            targets_output=targets_output,
        )
    except (OSError, ET.ParseError, ValueError, json.JSONDecodeError, csv.Error) as exc:
        print(f"identity pack scaffold failed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps({"drawio": str(outputs[0]), "spec": str(outputs[1]), "targets": str(outputs[2])}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
