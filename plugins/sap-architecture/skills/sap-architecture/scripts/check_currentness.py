#!/usr/bin/env python3
"""Check pinned SAP diagram sources and dated identity claims for staleness."""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Iterable

SKILL_DIR = Path(__file__).resolve().parent.parent
DEFAULT_CONTROL = SKILL_DIR / "assets" / "currentness.json"


def parse_date(value: Any, *, field: str) -> dt.date:
    try:
        return dt.date.fromisoformat(str(value))
    except ValueError as exc:
        raise ValueError(f"{field} must use YYYY-MM-DD") from exc


def github_latest(repository: str) -> str:
    url = f"https://api.github.com/repos/{repository}/releases/latest"
    request = urllib.request.Request(
        url,
        headers={"Accept": "application/vnd.github+json", "User-Agent": "sap-architecture-currentness-check"},
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        payload = json.load(response)
    tag = str(payload.get("tag_name", "")).strip()
    if not tag:
        raise ValueError(f"GitHub returned no tag_name for {repository}")
    return tag


def check(control: dict[str, Any], *, as_of: dt.date, live: bool) -> dict[str, Any]:
    max_age = int(control.get("max_age_days", 90))
    errors: list[str] = []
    warnings: list[str] = []
    upstream_results: list[dict[str, Any]] = []
    claim_results: list[dict[str, Any]] = []

    for item in control.get("upstreams", []):
        item_id = str(item.get("id", "unnamed-upstream"))
        observed_on = parse_date(item.get("observed_on"), field=f"{item_id}.observed_on")
        age = (as_of - observed_on).days
        result = {
            "id": item_id,
            "observed": str(item.get("latest_observed", "")),
            "observed_on": observed_on.isoformat(),
            "age_days": age,
            "status": "current",
        }
        if age < 0:
            errors.append(f"{item_id}: observed_on is after the as-of date")
            result["status"] = "invalid-date"
        elif age > max_age:
            errors.append(f"{item_id}: release observation is {age} days old (limit {max_age})")
            result["status"] = "stale"
        bundled = str(item.get("bundled_revision", "")).strip()
        if bundled in {"", "unknown", "hash-pinned-only"}:
            warnings.append(f"{item_id}: bundled revision is {bundled or 'not recorded'}; retain hash verification")
        if live:
            repository = str(item.get("repository", "")).strip()
            if not repository:
                errors.append(f"{item_id}: repository is required for --live")
                result["status"] = "invalid-control"
            else:
                try:
                    result["live_latest"] = github_latest(repository)
                except (OSError, ValueError, urllib.error.URLError, json.JSONDecodeError) as exc:
                    errors.append(f"{item_id}: live release lookup failed: {exc}")
                    result["status"] = "lookup-failed"
                else:
                    if result["live_latest"] != result["observed"]:
                        errors.append(
                            f"{item_id}: observed {result['observed']} but live latest is {result['live_latest']}"
                        )
                        result["status"] = "release-changed"
        upstream_results.append(result)

    for claim in control.get("dated_claims", []):
        claim_id = str(claim.get("id", "unnamed-claim"))
        checked_on = parse_date(claim.get("checked_on"), field=f"{claim_id}.checked_on")
        age = (as_of - checked_on).days
        result = {"id": claim_id, "checked_on": checked_on.isoformat(), "age_days": age, "status": "current"}
        if not str(claim.get("scope", "")).strip() or not str(claim.get("source_url", "")).startswith("https://"):
            errors.append(f"{claim_id}: dated claim requires scoped text and an HTTPS source")
            result["status"] = "invalid-control"
        elif age < 0:
            errors.append(f"{claim_id}: checked_on is after the as-of date")
            result["status"] = "invalid-date"
        elif age > max_age:
            errors.append(f"{claim_id}: claim review is {age} days old (limit {max_age})")
            result["status"] = "stale"
        if claim.get("deadline"):
            deadline = parse_date(claim["deadline"], field=f"{claim_id}.deadline")
            days_remaining = (deadline - as_of).days
            result.update({"deadline": deadline.isoformat(), "days_remaining": days_remaining})
            if days_remaining < 0:
                errors.append(f"{claim_id}: recorded deadline passed {-days_remaining} days ago; revalidate the claim")
                result["status"] = "deadline-passed"
            elif days_remaining <= 180:
                warnings.append(f"{claim_id}: deadline is in {days_remaining} days; keep the scenario-specific scope visible")
        claim_results.append(result)

    return {
        "schema_version": 1,
        "as_of": as_of.isoformat(),
        "ok": not errors,
        "errors": errors,
        "warnings": warnings,
        "upstreams": upstream_results,
        "dated_claims": claim_results,
    }


def main(argv: Iterable[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("control", type=Path, nargs="?", default=DEFAULT_CONTROL)
    ap.add_argument("--as-of", type=dt.date.fromisoformat, default=dt.date.today())
    ap.add_argument("--live", action="store_true", help="Compare observed tags with GitHub's latest releases")
    args = ap.parse_args(list(argv) if argv is not None else None)
    try:
        control = json.loads(args.control.read_text(encoding="utf-8"))
        if not isinstance(control, dict) or control.get("schema_version") != 1:
            raise ValueError("currentness control requires schema_version 1")
        report = check(control, as_of=args.as_of, live=args.live)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"currentness check failed: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(report, indent=2))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
