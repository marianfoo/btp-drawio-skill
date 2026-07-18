#!/usr/bin/env python3
"""Validate a draw.io diagram against a pre-authored semantic specification.

The visual fingerprint proves SAP-style fidelity. This validator proves that the
candidate still contains the components and directed relationships agreed before
template selection.
"""
from __future__ import annotations

import argparse
import html
import json
import re
import sys
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable


LABEL_ATTRS = ("value", "label", "name")
CLAIM_STATES = {
    "product-capability",
    "proposed-design",
    "configured-client-state",
    "client-confirmation",
    "protocol-specific-exception",
}


@dataclass(frozen=True)
class SemanticIssue:
    code: str
    message: str


@dataclass
class SemanticReport:
    errors: list[SemanticIssue] = field(default_factory=list)
    warnings: list[SemanticIssue] = field(default_factory=list)
    matched: dict[str, list[str]] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return not self.errors


@dataclass(frozen=True)
class DiagramSemantics:
    labels_by_id: dict[str, str]
    all_labels: list[str]
    node_labels: list[str]
    zone_labels: list[str]
    edges: list[tuple[str, str, str, str, str]]


def clean_label(value: str) -> str:
    value = html.unescape(value or "")
    value = re.sub(r"<br\s*/?>", " ", value, flags=re.I)
    value = re.sub(r"<[^>]+>", " ", value)
    value = value.replace("&nbsp;", " ")
    return re.sub(r"\s+", " ", value).strip()


def normalized(value: str) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", clean_label(value).lower()))


def aliases(value: Any, *, field_name: str) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, list) and all(isinstance(item, str) for item in value):
        return value
    if isinstance(value, dict):
        name = value.get("name")
        extras = value.get("aliases", [])
        if isinstance(name, str) and isinstance(extras, list) and all(isinstance(item, str) for item in extras):
            return [name, *extras]
    raise ValueError(f"{field_name} must be a string, string list, or object with name/aliases")


def label_matches(label: str, candidates: Iterable[str]) -> bool:
    label_norm = normalized(label)
    label_tokens = set(label_norm.split())
    for candidate in candidates:
        candidate_norm = normalized(candidate)
        if not candidate_norm:
            continue
        candidate_tokens = set(candidate_norm.split())
        if candidate_norm == label_norm:
            return True
        if len(candidate_tokens) < 2:
            continue
        if candidate_norm in label_norm:
            return True
        if candidate_tokens and candidate_tokens <= label_tokens:
            return True
    return False


def diagram_scope(root: ET.Element, page: str | int | None = None) -> ET.Element:
    if root.tag == "mxfile":
        diagrams = root.findall("diagram")
        if page is None:
            if diagrams:
                return diagrams[0]
        elif isinstance(page, int):
            if 0 <= page < len(diagrams):
                return diagrams[page]
        else:
            match = next((diagram for diagram in diagrams if diagram.get("name") == page), None)
            if match is not None:
                return match
        raise ValueError(f"diagram page not found: {page!r}")
    return root


def first_diagram_scope(root: ET.Element) -> ET.Element:
    """Backward-compatible alias for callers that intentionally inspect page one."""
    return diagram_scope(root)


def extract_semantics(path: Path, page: str | int | None = None) -> DiagramSemantics:
    root = ET.parse(path).getroot()
    scope = diagram_scope(root, page)
    labels_by_id: dict[str, str] = {}
    cell_by_id: dict[str, ET.Element] = {}

    for elem in scope.iter():
        elem_id = elem.get("id")
        if elem_id == "guarded-provenance":
            continue
        raw = next((elem.get(attr) for attr in LABEL_ATTRS if elem.get(attr) is not None), None)
        label = clean_label(raw or "")
        if elem_id and label:
            labels_by_id[elem_id] = label
        if elem.tag == "mxCell" and elem_id:
            cell_by_id[elem_id] = elem
        if elem.tag == "UserObject":
            wrapper_label = label
            for child in elem:
                if child.tag != "mxCell":
                    continue
                child_id = child.get("id") or elem_id
                if child_id:
                    cell_by_id[child_id] = child
                    if wrapper_label:
                        labels_by_id[child_id] = wrapper_label

    def endpoint_label(cell_id: str) -> str:
        seen: set[str] = set()
        current = cell_id
        while current and current not in seen:
            seen.add(current)
            if labels_by_id.get(current):
                return labels_by_id[current]
            cell = cell_by_id.get(current)
            if cell is None:
                break
            current = cell.get("parent") or ""
        return ""

    edges: list[tuple[str, str, str, str, str]] = []
    for edge in scope.iter("mxCell"):
        if edge.get("edge") != "1":
            continue
        source_id = edge.get("data-semantic-source") or edge.get("source") or ""
        target_id = edge.get("data-semantic-target") or edge.get("target") or ""
        edge_label = clean_label(edge.get("value") or "")
        edges.append((source_id, target_id, endpoint_label(source_id), endpoint_label(target_id), edge_label))

    all_labels = sorted(set(label for label in labels_by_id.values() if label))
    node_labels: set[str] = set()
    zone_labels: set[str] = set()
    for cell_id, cell in cell_by_id.items():
        if cell.get("vertex") != "1" or not labels_by_id.get(cell_id):
            continue
        style = cell.get("style") or ""
        geometry = cell.find("mxGeometry")
        try:
            width = float(geometry.get("width") or 0) if geometry is not None else 0
            height = float(geometry.get("height") or 0) if geometry is not None else 0
        except ValueError:
            width = height = 0
        is_zone = "arcSize=16" in style and "absoluteArcSize=1" in style and width >= 200 and height >= 120
        is_pill = "arcSize=50" in style
        if is_zone:
            zone_labels.add(labels_by_id[cell_id])
        elif not is_pill:
            node_labels.add(labels_by_id[cell_id])
    return DiagramSemantics(
        labels_by_id=labels_by_id,
        all_labels=all_labels,
        node_labels=sorted(node_labels),
        zone_labels=sorted(zone_labels),
        edges=edges,
    )


def load_spec(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("semantic specification must be a JSON object")
    if data.get("schema_version") not in {1, 2}:
        raise ValueError("semantic specification requires schema_version 1 or 2")
    return data


def validate_claims(spec: dict[str, Any], report: SemanticReport) -> None:
    claims = spec.get("claims", [])
    if not isinstance(claims, list):
        raise ValueError("claims must be a list")
    seen: set[str] = set()
    for index, claim in enumerate(claims):
        if not isinstance(claim, dict):
            raise ValueError(f"claims[{index}] must be an object")
        claim_id = str(claim.get("id", "")).strip()
        state = str(claim.get("state", "")).strip()
        text = str(claim.get("text", "")).strip()
        if not claim_id or claim_id in seen:
            report.errors.append(SemanticIssue("invalid-claim-id", f"claim {index + 1} requires a unique id"))
            continue
        seen.add(claim_id)
        if not text:
            report.errors.append(SemanticIssue("missing-claim-text", f"claim {claim_id} requires text"))
        if state not in CLAIM_STATES:
            report.errors.append(SemanticIssue("invalid-claim-state", f"claim {claim_id} has invalid state: {state}"))
            continue
        if state == "product-capability":
            if not str(claim.get("source_url", "")).startswith("https://") or not str(claim.get("checked_on", "")).strip():
                report.errors.append(
                    SemanticIssue(
                        "unverified-product-capability",
                        f"claim {claim_id} requires source_url and checked_on",
                    )
                )
        elif state == "proposed-design":
            if claim.get("decision_status") not in {"proposed", "assumption", "client-confirm"}:
                report.errors.append(
                    SemanticIssue(
                        "unbounded-proposed-design",
                        f"claim {claim_id} requires decision_status proposed, assumption, or client-confirm",
                    )
                )
        elif state == "configured-client-state":
            if not str(claim.get("evidence", "")).strip():
                report.errors.append(
                    SemanticIssue(
                        "unproven-client-state",
                        f"claim {claim_id} requires a client evidence reference",
                    )
                )
        elif state == "client-confirmation":
            if not str(claim.get("confirmation_needed", "")).strip():
                report.errors.append(
                    SemanticIssue(
                        "missing-confirmation-boundary",
                        f"claim {claim_id} requires confirmation_needed",
                    )
                )
        elif state == "protocol-specific-exception":
            required = ("protocol", "scope", "source_url")
            missing = [key for key in required if not str(claim.get(key, "")).strip()]
            if missing:
                report.errors.append(
                    SemanticIssue(
                        "unscoped-protocol-exception",
                        f"claim {claim_id} requires {', '.join(missing)}",
                    )
                )


def validate_page_spec(
    diagram: DiagramSemantics,
    spec: dict[str, Any],
    report: SemanticReport,
    *,
    key_prefix: str = "",
) -> None:

    def require_labels(key: str, values: Any, pool: list[str]) -> None:
        if values is None:
            return
        if not isinstance(values, list):
            raise ValueError(f"{key} must be a list")
        matched: list[str] = []
        for index, value in enumerate(values):
            wanted = aliases(value, field_name=f"{key}[{index}]")
            actual = next((label for label in pool if label_matches(label, wanted)), None)
            if actual is None:
                report.errors.append(SemanticIssue(f"missing-{key}", f"missing required {key[:-1]}: {wanted[0]}"))
            else:
                matched.append(actual)
        report.matched[f"{key_prefix}{key}"] = matched

    require_labels("required_nodes", spec.get("required_nodes", []), diagram.node_labels)
    require_labels("required_zones", spec.get("required_zones", []), diagram.zone_labels)
    require_labels("required_terms", spec.get("required_terms", []), diagram.all_labels)

    forbidden = spec.get("forbidden_terms", [])
    if not isinstance(forbidden, list):
        raise ValueError("forbidden_terms must be a list")
    for index, value in enumerate(forbidden):
        unwanted = aliases(value, field_name=f"forbidden_terms[{index}]")
        actual = next((label for label in diagram.all_labels if label_matches(label, unwanted)), None)
        if actual is not None:
            report.errors.append(SemanticIssue("forbidden-term", f"forbidden term remains: {actual}"))

    flows = spec.get("required_flows", [])
    if not isinstance(flows, list):
        raise ValueError("required_flows must be a list")
    matched_flows: list[str] = []
    for index, flow in enumerate(flows):
        if not isinstance(flow, dict) or "from" not in flow or "to" not in flow:
            raise ValueError(f"required_flows[{index}] requires from and to")
        source_aliases = aliases(flow["from"], field_name=f"required_flows[{index}].from")
        target_aliases = aliases(flow["to"], field_name=f"required_flows[{index}].to")
        bidirectional = bool(flow.get("bidirectional", False))
        found = False
        for _source_id, _target_id, source_label, target_label, _edge_label in diagram.edges:
            forward = label_matches(source_label, source_aliases) and label_matches(target_label, target_aliases)
            reverse = bidirectional and label_matches(source_label, target_aliases) and label_matches(target_label, source_aliases)
            if forward or reverse:
                found = True
                matched_flows.append(f"{source_label} -> {target_label}")
                break
        if not found:
            direction = "<->" if bidirectional else "->"
            report.errors.append(
                SemanticIssue("missing-flow", f"missing required flow: {source_aliases[0]} {direction} {target_aliases[0]}")
            )
    report.matched[f"{key_prefix}required_flows"] = matched_flows

    expected_level = spec.get("level")
    if expected_level and expected_level not in {"L0", "L1", "L2"}:
        report.warnings.append(SemanticIssue("unknown-level", f"non-standard level in specification: {expected_level}"))


def validate_semantics(drawio: Path, spec_path: Path) -> SemanticReport:
    spec = load_spec(spec_path)
    report = SemanticReport()
    if spec.get("schema_version") == 1:
        validate_page_spec(extract_semantics(drawio), spec, report)
        return report

    status = spec.get("status")
    if status not in {"internal-draft", "external-safe-generic", "client-specific-final-candidate"}:
        report.errors.append(SemanticIssue("invalid-pack-status", f"invalid pack status: {status}"))
    validate_claims(spec, report)
    pages = spec.get("pages")
    if not isinstance(pages, list) or not pages:
        raise ValueError("schema_version 2 requires a non-empty pages list")
    root = ET.parse(drawio).getroot()
    actual_names = [diagram.get("name") or "" for diagram in root.findall("diagram")] if root.tag == "mxfile" else [""]
    expected_names: list[str] = []
    for index, page_spec in enumerate(pages):
        if not isinstance(page_spec, dict):
            raise ValueError(f"pages[{index}] must be an object")
        page_name = str(page_spec.get("name", "")).strip()
        if not page_name:
            raise ValueError(f"pages[{index}] requires name")
        if page_name in expected_names:
            raise ValueError(f"duplicate page specification: {page_name}")
        expected_names.append(page_name)
        try:
            semantics = extract_semantics(drawio, page_name)
        except ValueError:
            report.errors.append(SemanticIssue("missing-page", f"missing required diagram page: {page_name}"))
            continue
        validate_page_spec(semantics, page_spec, report, key_prefix=f"pages[{page_name}].")
    unexpected = [name for name in actual_names if name not in expected_names]
    missing_specs = [name for name in expected_names if name not in actual_names]
    for name in unexpected:
        report.warnings.append(SemanticIssue("uncontrolled-page", f"diagram page has no semantic specification: {name}"))
    for name in missing_specs:
        if not any(issue.code == "missing-page" and name in issue.message for issue in report.errors):
            report.errors.append(SemanticIssue("missing-page", f"missing required diagram page: {name}"))
    return report


def print_text(report: SemanticReport) -> None:
    for issue in report.errors:
        print(f"ERROR [{issue.code}] {issue.message}")
    for issue in report.warnings:
        print(f"WARN  [{issue.code}] {issue.message}")
    print(f"semantic validation: {len(report.errors)} error(s), {len(report.warnings)} warning(s)")


def main(argv: Iterable[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("drawio", type=Path)
    ap.add_argument("spec", type=Path)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(list(argv) if argv is not None else None)
    if not args.drawio.exists() or not args.spec.exists():
        print("drawio and spec files must exist", file=sys.stderr)
        return 2
    try:
        report = validate_semantics(args.drawio, args.spec)
    except (ET.ParseError, OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"semantic validation failed: {exc}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(asdict(report), indent=2))
    else:
        print_text(report)
    return 0 if report.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
