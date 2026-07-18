#!/usr/bin/env python3
"""Convert controlled topology rows into a draw.io CSV-import draft."""
from __future__ import annotations

import argparse
import csv
import io
import json
import sys
from pathlib import Path
from typing import Any, Iterable

THIS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(THIS_DIR))
import validate_semantics  # type: ignore[import-not-found]  # noqa: E402

REQUIRED = {"id", "label", "connect_to", "protocol", "claim_state"}
STATE_STYLES = {
    "product-capability": ("#d5e8d4", "#82b366"),
    "proposed-design": ("#fff2cc", "#d6b656"),
    "configured-client-state": ("#dae8fc", "#6c8ebf"),
    "client-confirmation": ("#f8cecc", "#b85450"),
    "protocol-specific-exception": ("#e1d5e7", "#9673a6"),
}


def build(rows: list[dict[str, str]]) -> str:
    if not rows:
        raise ValueError("topology CSV requires at least one row")
    ids: set[str] = set()
    claims: list[dict[str, Any]] = []
    output_rows: list[dict[str, str]] = []
    for index, row in enumerate(rows, start=2):
        missing = sorted(key for key in REQUIRED if not str(row.get(key, "")).strip() and key != "connect_to")
        node_id = str(row.get("id", "")).strip()
        if missing or not node_id or node_id in ids:
            raise ValueError(f"row {index} requires unique id and non-empty {', '.join(sorted(REQUIRED - {'connect_to'}))}")
        ids.add(node_id)
        state = str(row.get("claim_state", "")).strip()
        claim: dict[str, Any] = {
            "id": str(row.get("claim_id", "")).strip() or f"topology-{index - 1:03d}",
            "text": str(row.get("claim_text", "")).strip() or str(row.get("label", "")).strip(),
            "state": state,
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
            if str(row.get(key, "")).strip():
                claim[key] = str(row[key]).strip()
        claims.append(claim)
        fill, stroke = STATE_STYLES.get(state, ("#f5f5f5", "#666666"))
        output_rows.append(
            {
                "id": node_id,
                "label": str(row.get("label", "")).strip(),
                "connect_to": str(row.get("connect_to", "")).strip(),
                "protocol": str(row.get("protocol", "")).strip(),
                "fill": fill,
                "stroke": stroke,
            }
        )
    unknown = sorted({row["connect_to"] for row in output_rows if row["connect_to"]} - ids)
    if unknown:
        raise ValueError(f"connect_to references unknown ids: {', '.join(unknown)}")
    report = validate_semantics.SemanticReport()
    validate_semantics.validate_claims({"claims": claims}, report)
    if report.errors:
        raise ValueError("; ".join(issue.message for issue in report.errors))

    buffer = io.StringIO(newline="")
    buffer.write("# DRAFT ONLY - integrate into a template-derived .drawio page before delivery\n")
    buffer.write("# label: %label%\n")
    buffer.write("# style: rounded=1;whiteSpace=wrap;html=1;fillColor=%fill%;strokeColor=%stroke%;\n")
    buffer.write("# identity: id\n")
    buffer.write('# connect: {"from":"connect_to","to":"id","invert":true,"label":"protocol","style":"endArrow=block;html=1;"}\n')
    buffer.write("# layout: auto\n")
    writer = csv.DictWriter(buffer, fieldnames=["id", "label", "connect_to", "protocol", "fill", "stroke"])
    writer.writeheader()
    writer.writerows(output_rows)
    return buffer.getvalue()


def main(argv: Iterable[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("input", type=Path)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args(list(argv) if argv is not None else None)
    try:
        with args.input.open(newline="", encoding="utf-8-sig") as handle:
            rows = [{str(k): str(v or "").strip() for k, v in row.items()} for row in csv.DictReader(handle)]
        output = build(rows)
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(output, encoding="utf-8")
    except (OSError, ValueError, csv.Error) as exc:
        print(f"CSV variation draft failed: {exc}", file=sys.stderr)
        return 1
    print(args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
