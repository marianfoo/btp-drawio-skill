#!/usr/bin/env python3
"""Create a controlled Mermaid identity sequence draft from structured JSON."""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Iterable

THIS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(THIS_DIR))
import validate_semantics  # type: ignore[import-not-found]  # noqa: E402

SAFE_ID = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")


def mermaid_text(value: Any) -> str:
    return str(value).replace("\r", " ").replace("\n", " ").replace('"', "'").strip()


def build(payload: dict[str, Any]) -> str:
    if payload.get("schema_version") != 1 or payload.get("status") != "draft":
        raise ValueError("sequence input requires schema_version 1 and status draft")
    participants = payload.get("participants")
    messages = payload.get("messages")
    if not isinstance(participants, list) or not participants or not isinstance(messages, list) or not messages:
        raise ValueError("sequence input requires non-empty participants and messages")
    participant_ids: set[str] = set()
    lines = ["%% DRAFT ONLY — integrate into a template-derived .drawio page before delivery", "sequenceDiagram"]
    for index, participant in enumerate(participants, start=1):
        if not isinstance(participant, dict):
            raise ValueError(f"participant {index} must be an object")
        participant_id = str(participant.get("id", ""))
        label = mermaid_text(participant.get("label", ""))
        if not SAFE_ID.fullmatch(participant_id) or participant_id in participant_ids or not label:
            raise ValueError(f"participant {index} requires a unique safe id and label")
        participant_ids.add(participant_id)
        lines.append(f"    participant {participant_id} as {label}")

    claims: list[dict[str, Any]] = []
    for index, message in enumerate(messages, start=1):
        if not isinstance(message, dict):
            raise ValueError(f"message {index} must be an object")
        source = str(message.get("from", ""))
        target = str(message.get("to", ""))
        label = mermaid_text(message.get("label", ""))
        protocol = mermaid_text(message.get("protocol", ""))
        if source not in participant_ids or target not in participant_ids or not label:
            raise ValueError(f"message {index} requires known from/to participants and a label")
        claim = {
            key: value
            for key, value in message.items()
            if key
            in {
                "state",
                "source_url",
                "checked_on",
                "decision_status",
                "evidence",
                "confirmation_needed",
                "protocol",
                "scope",
            }
        }
        claim.update({"id": f"sequence-{index:03d}", "text": label})
        claims.append(claim)
        arrow = "-->>" if str(message.get("response", "")).lower() == "true" else "->>"
        visible = f"{protocol}: {label}" if protocol else label
        lines.append(f"    {source}{arrow}{target}: {visible}")
    report = validate_semantics.SemanticReport()
    validate_semantics.validate_claims({"claims": claims}, report)
    if report.errors:
        raise ValueError("; ".join(issue.message for issue in report.errors))
    return "\n".join(lines) + "\n"


def main(argv: Iterable[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("input", type=Path)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args(list(argv) if argv is not None else None)
    try:
        payload = json.loads(args.input.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("sequence input must be an object")
        output = build(payload)
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(output, encoding="utf-8")
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"sequence draft failed: {exc}", file=sys.stderr)
        return 1
    print(args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
