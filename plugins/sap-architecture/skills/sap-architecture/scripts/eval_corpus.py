#!/usr/bin/env python3
"""Evaluate SAP Architecture Center diagram fidelity across a reference corpus.

The harness is intentionally conservative:

* Generated artifacts are written below .cache/ by default.
* Long Ollama runs are opt-in.
* The first Ollama implementation asks the model for a compact generation plan
  and then creates a template-preserving candidate. This verifies the local LLM
  plumbing without depending on the model to emit flawless draw.io XML.

Subcommands:
  inventory  list bundled or external SAP .drawio references
  describe   extract natural-language prompts from references
  dry-run    show the cases that would be evaluated, no output files
  generate   create candidates under .cache/
  score      validate and score an existing candidate
  run        describe -> generate -> autofix -> validate -> score -> report
"""
from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
import shutil
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from compare import compare, fingerprint
from select_reference import score as select_reference_score

SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_DIR = SCRIPT_DIR.parent
DEFAULT_REFERENCE_DIR = SKILL_DIR / "assets" / "reference-examples"
DEFAULT_OUT_DIR = Path(".cache") / "sap-architecture-eval"
DEFAULT_MODEL = "qwen3.6:35b-a3b-nvfp4"
DEFAULT_TIMEOUT_SECONDS = 600
VISIBLE_TEXT_LIMIT = 1800
ANSI_RE = re.compile(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")
CONTROL_RE = re.compile(r"[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]")
EXPECTED_MODEL_KEYS = {"title", "subtitle", "services", "flow_steps", "style_risks"}


@dataclass
class EvalCase:
    case_id: str
    reference: str
    family: str
    title: str
    description: str
    selected_template: str
    selected_template_score: float


@dataclass
class AttemptResult:
    attempt: int
    candidate: str | None = None
    raw_model_output: str | None = None
    model_json: str | None = None
    model_error: str | None = None
    autofix_rc: int | None = None
    validate_rc: int | None = None
    validate_errors: int = 0
    validate_warnings: int = 0
    target_score: float | None = None
    corpus_score: float | None = None
    best_corpus_reference: str | None = None
    passed: bool = False
    failure: str | None = None


@dataclass
class CaseResult:
    case: EvalCase
    attempts: list[AttemptResult] = field(default_factory=list)
    passed: bool = False
    best_score: float = 0.0


def default_reference_inputs(args: argparse.Namespace) -> list[Path]:
    return args.references or [DEFAULT_REFERENCE_DIR]


def collect_references(paths: list[Path]) -> list[Path]:
    refs: list[Path] = []
    for p in paths:
        if p.is_dir():
            refs.extend(sorted(p.rglob("*.drawio")))
        elif p.suffix.lower() == ".drawio":
            refs.append(p)
    return sorted(dict.fromkeys(refs))


def clean_text(value: str) -> str:
    value = html.unescape(value)
    value = re.sub(r"<br\s*/?>", " ", value, flags=re.I)
    value = re.sub(r"<[^>]+>", " ", value)
    value = re.sub(r"&nbsp;", " ", value)
    value = re.sub(r"\s+", " ", value).strip()
    return value


def visible_drawio_labels(path: Path, limit: int = VISIBLE_TEXT_LIMIT) -> list[str]:
    labels: list[str] = []
    try:
        root = ET.parse(path).getroot()
    except ET.ParseError:
        return labels

    for elem in root.iter():
        for attr in ("name", "label", "value"):
            raw = elem.get(attr)
            if not raw:
                continue
            text = clean_text(raw)
            if not text or text in labels:
                continue
            labels.append(text)
            if sum(len(x) for x in labels) >= limit:
                return labels
    return labels


def nearby_markdown_text(path: Path, limit: int = 1200) -> str:
    chunks: list[str] = []
    seen: set[Path] = set()
    excluded = {"notice.md", "skill.md", "readme.md"}
    # In the bundled plugin corpus, Markdown above reference-examples/ is plugin
    # documentation, not source scenario text. For cloned SAP repos, useful
    # Markdown normally lives beside or one/two levels above the drawio file.
    max_depth = 2
    for parent in [path.parent, *list(path.parents)[:max_depth]]:
        for md in sorted(parent.glob("*.md"))[:3]:
            if md.name.lower() in excluded:
                continue
            if md in seen:
                continue
            seen.add(md)
            try:
                text = md.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            lines = []
            for line in text.splitlines():
                stripped = line.strip()
                if stripped.startswith("#") or stripped.startswith("- ") or stripped.startswith("This ") or stripped.startswith("The "):
                    lines.append(stripped)
                if len(" ".join(lines)) >= limit:
                    break
            if lines:
                chunks.append(clean_text(" ".join(lines)))
        if sum(len(x) for x in chunks) >= limit:
            break
    return clean_text(" ".join(chunks))[:limit]


def family_for(path: Path) -> str:
    m = re.search(r"(RA\d{4})", path.name)
    if m:
        return m.group(1)
    m = re.search(r"(RA\d{4})", str(path))
    if m:
        return m.group(1)
    if path.name.startswith("btp_"):
        return "btp"
    return "unknown"


def title_for(path: Path, labels: list[str]) -> str:
    if labels:
        first = labels[0]
        if 4 <= len(first) <= 140:
            return first
    return path.stem.replace("_", " ").replace("-", " ")


def case_id_for(path: Path) -> str:
    digest = hashlib.sha1(str(path).encode("utf-8")).hexdigest()[:8]
    stem = re.sub(r"[^A-Za-z0-9]+", "-", path.stem).strip("-").lower()[:48]
    return f"{stem}-{digest}"


def build_description(path: Path) -> tuple[str, str]:
    labels = visible_drawio_labels(path)
    title = title_for(path, labels)
    md = nearby_markdown_text(path)
    hints = "; ".join(labels[:18])
    parts = [
        f"Create an SAP Architecture Center style diagram for: {title}.",
        f"Reference family: {family_for(path)}.",
    ]
    if hints:
        parts.append(f"Visible diagram labels and scenario hints: {hints}.")
    if md:
        parts.append(f"Nearby reference architecture text: {md}.")
    parts.append("Preserve SAP visual conventions: Horizon palette, SAP service icons, zone rhythm, connector semantics, and readable labels.")
    return title, clean_text(" ".join(parts))


def select_template(description: str, references: list[Path]) -> tuple[Path, float]:
    ranked = sorted((select_reference_score(p, description) for p in references), key=lambda c: (-c.score, c.path))
    if not ranked:
        raise ValueError("no references available for template selection")
    return Path(ranked[0].path), ranked[0].score


def build_cases(references: list[Path], limit: int | None = None) -> list[EvalCase]:
    cases: list[EvalCase] = []
    selector_refs = collect_references([DEFAULT_REFERENCE_DIR])
    for ref in references[: limit or None]:
        title, description = build_description(ref)
        selected, selected_score = select_template(description, selector_refs)
        cases.append(
            EvalCase(
                case_id=case_id_for(ref),
                reference=str(ref),
                family=family_for(ref),
                title=title,
                description=description,
                selected_template=str(selected),
                selected_template_score=selected_score,
            )
        )
    return cases


def run_id() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")


def prompt_for_ollama(case: EvalCase) -> str:
    return f"""You are helping test an SAP Architecture Center draw.io generation skill.

Return JSON only. Do not return XML. Do not use markdown fences.

Create a concise generation plan for this request:
{case.description}

Use the selected SAP template as the base, not a blank canvas:
{case.selected_template}

Available local SAP starter-kit assets:
- extract_icon.py for BTP service icons
- extract_asset.py for generic icons, connector presets, area/default shapes, number markers, SAP brand names, text elements, and annotation/interface pills

Avoid these visual risks:
- generic draw.io colors such as #dae8fc, #d5e8d4, #f8cecc, or #fff2cc
- hand-authored arrows when a connector preset exists
- external image URLs
- clipped labels or oversized text inside service cards
- replacing SAP grey-circle service icons with blank mxgraph stencils

Use these keys:
title: short diagram title
subtitle: one sentence subtitle
services: array of important SAP or external services
flow_steps: array of numbered flow step labels
style_risks: array of visual risks to avoid
"""


def sanitize_model_text(text: str) -> str:
    """Remove terminal control noise while preserving useful model text."""
    text = ANSI_RE.sub("", text)
    text = CONTROL_RE.sub("", text)
    return text.replace("\r", "\n")


def extract_json_object(text: str) -> tuple[str | None, str | None]:
    stripped = sanitize_model_text(text).strip()
    stripped = re.sub(r"```(?:json)?", "", stripped, flags=re.I).replace("```", "")
    decoder = json.JSONDecoder()
    parsed_objects: list[dict[str, Any]] = []

    for match in re.finditer(r"{", stripped):
        try:
            parsed, _ = decoder.raw_decode(stripped[match.start() :])
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            parsed_objects.append(parsed)

    if not parsed_objects:
        return None, "no JSON object found in model output"

    preferred = [obj for obj in parsed_objects if EXPECTED_MODEL_KEYS.intersection(obj)]
    parsed = preferred[-1] if preferred else parsed_objects[-1]
    return json.dumps(parsed, indent=2, sort_keys=True), None


def call_ollama(case: EvalCase, model: str, timeout_seconds: int) -> tuple[str, str | None, str | None]:
    prompt = prompt_for_ollama(case)
    proc = subprocess.run(
        ["ollama", "run", model, "--format", "json", "--hidethinking", "--nowordwrap", "--think", "false"],
        input=prompt,
        text=True,
        capture_output=True,
        timeout=timeout_seconds,
        check=False,
    )
    raw = proc.stdout.strip()
    if proc.stderr.strip():
        raw = raw + ("\n" if raw else "") + proc.stderr.strip()
    if proc.returncode != 0:
        return raw, None, f"ollama exited {proc.returncode}"
    model_json, parse_error = extract_json_object(raw)
    return raw, model_json, parse_error


def make_candidate_from_template(case: EvalCase, candidate_path: Path) -> None:
    candidate_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(case.selected_template, candidate_path)


def run_cli(args: list[str], timeout_seconds: int | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, text=True, capture_output=True, timeout=timeout_seconds, check=False)


def validate_candidate(candidate: Path) -> tuple[int, int, int, list[dict[str, Any]]]:
    proc = run_cli([sys.executable, str(SCRIPT_DIR / "validate.py"), "--json", str(candidate)])
    try:
        report = json.loads(proc.stdout)[0]
    except (json.JSONDecodeError, IndexError, KeyError):
        return proc.returncode, 999, 0, [{"category": "tool", "msg": proc.stderr or proc.stdout, "cell": None}]
    return proc.returncode, len(report.get("errors", [])), len(report.get("warnings", [])), report.get("errors", [])


def best_corpus_score(candidate: Path, references: list[Path]) -> tuple[float, str | None]:
    cand_fp = fingerprint(candidate)
    best_score = 0.0
    best_ref: str | None = None
    for ref in references:
        result = compare(fingerprint(ref), cand_fp)
        if result.score > best_score:
            best_score = result.score
            best_ref = str(ref)
    return best_score, best_ref


def score_pair(reference: Path, candidate: Path) -> float:
    return compare(fingerprint(reference), fingerprint(candidate)).score


def run_one_attempt(
    case: EvalCase,
    attempt: int,
    case_dir: Path,
    generator: str,
    model: str,
    timeout_seconds: int,
    min_score: float,
    corpus_refs: list[Path],
    do_score: bool,
) -> AttemptResult:
    attempt_dir = case_dir / f"attempt-{attempt}"
    attempt_dir.mkdir(parents=True, exist_ok=True)
    result = AttemptResult(attempt=attempt)

    if generator == "ollama":
        try:
            raw, model_json, model_error = call_ollama(case, model, timeout_seconds)
        except subprocess.TimeoutExpired:
            result.model_error = f"ollama timed out after {timeout_seconds}s"
            result.failure = result.model_error
            return result
        result.raw_model_output = str(attempt_dir / "model-output.txt")
        (attempt_dir / "model-output.txt").write_text(raw, encoding="utf-8")
        cleaned = sanitize_model_text(raw)
        if cleaned != raw:
            (attempt_dir / "model-output.clean.txt").write_text(cleaned, encoding="utf-8")
        if model_json:
            result.model_json = str(attempt_dir / "model-output.json")
            (attempt_dir / "model-output.json").write_text(model_json, encoding="utf-8")
        if model_error:
            result.model_error = model_error
            (attempt_dir / "model-error.txt").write_text(model_error, encoding="utf-8")
    elif generator != "baseline":
        result.failure = f"unknown generator {generator!r}"
        return result

    candidate = attempt_dir / "candidate.drawio"
    make_candidate_from_template(case, candidate)
    result.candidate = str(candidate)

    if not do_score:
        result.passed = True
        return result

    autofix = run_cli([sys.executable, str(SCRIPT_DIR / "autofix.py"), "--write", str(candidate)])
    result.autofix_rc = autofix.returncode
    (attempt_dir / "autofix.stdout.txt").write_text(autofix.stdout, encoding="utf-8")
    (attempt_dir / "autofix.stderr.txt").write_text(autofix.stderr, encoding="utf-8")

    result.validate_rc, result.validate_errors, result.validate_warnings, validate_errors = validate_candidate(candidate)
    write_json(attempt_dir / "validate-errors.json", validate_errors)

    result.target_score = score_pair(Path(case.reference), candidate)
    result.corpus_score, result.best_corpus_reference = best_corpus_score(candidate, corpus_refs)
    result.passed = result.validate_errors == 0 and result.corpus_score >= min_score
    if not result.passed:
        result.failure = f"validator_errors={result.validate_errors}, corpus_score={result.corpus_score:.1f}"
    return result


def run_cases(
    cases: list[EvalCase],
    args: argparse.Namespace,
    do_score: bool,
) -> tuple[Path, list[CaseResult]]:
    rid = run_id()
    run_dir = args.out_dir / rid
    run_dir.mkdir(parents=True, exist_ok=True)
    corpus_refs = collect_references([DEFAULT_REFERENCE_DIR])
    results: list[CaseResult] = []

    write_json(run_dir / "cases.json", [asdict(c) for c in cases])

    for case in cases:
        case_dir = run_dir / "cases" / case.case_id
        write_json(case_dir / "case.json", asdict(case))
        case_result = CaseResult(case=case)
        for attempt in range(1, args.max_attempts + 1):
            attempt_result = run_one_attempt(
                case=case,
                attempt=attempt,
                case_dir=case_dir,
                generator=args.generator,
                model=args.model,
                timeout_seconds=args.timeout_seconds,
                min_score=args.min_score,
                corpus_refs=corpus_refs,
                do_score=do_score,
            )
            case_result.attempts.append(attempt_result)
            if attempt_result.corpus_score is not None:
                case_result.best_score = max(case_result.best_score, attempt_result.corpus_score)
            if attempt_result.passed:
                case_result.passed = True
                break
            if attempt_result.failure and not args.continue_on_error and attempt == args.max_attempts:
                break
        write_json(case_dir / "result.json", asdict(case_result))
        results.append(case_result)
        if not case_result.passed and not args.continue_on_error:
            break

    write_reports(run_dir, results, args.min_score)
    return run_dir, results


def write_reports(run_dir: Path, results: list[CaseResult], min_score: float) -> None:
    passed = sum(1 for r in results if r.passed)
    scores = [r.best_score for r in results if r.best_score]
    best_attempts = {
        r.case.case_id: max(r.attempts, key=lambda a: a.corpus_score or 0.0) if r.attempts else None
        for r in results
    }
    summary = {
        "run_dir": str(run_dir),
        "case_count": len(results),
        "passed": passed,
        "failed": len(results) - passed,
        "min_score": min_score,
        "average_best_score": round(sum(scores) / len(scores), 1) if scores else 0.0,
        "results": [asdict(r) for r in results],
    }
    write_json(run_dir / "summary.json", summary)

    lines = [
        "# SAP Architecture Evaluation Report",
        "",
        f"- Cases: {len(results)}",
        f"- Passed: {passed}",
        f"- Failed: {len(results) - passed}",
        f"- Minimum corpus score: {min_score}",
        f"- Average best score: {summary['average_best_score']}",
        "",
        "| Case | Family | Passed | Best score | Target score | Candidate |",
        "|---|---|---:|---:|---:|---|",
    ]
    for r in results:
        best_attempt = best_attempts[r.case.case_id]
        target = best_attempt.target_score if best_attempt and best_attempt.target_score is not None else 0.0
        candidate = best_attempt.candidate if best_attempt and best_attempt.candidate else ""
        lines.append(
            f"| `{r.case.case_id}` | {r.case.family} | {str(r.passed).lower()} | "
            f"{r.best_score:.1f} | {target:.1f} | `{candidate}` |"
        )

    family_stats: dict[str, dict[str, Any]] = {}
    for r in results:
        stats = family_stats.setdefault(r.case.family, {"cases": 0, "passed": 0, "scores": []})
        stats["cases"] += 1
        stats["passed"] += 1 if r.passed else 0
        if r.best_score:
            stats["scores"].append(r.best_score)

    lines.extend(["", "## Family Summary", "", "| Family | Cases | Passed | Avg best | Min best |", "|---|---:|---:|---:|---:|"])
    for family, stats in sorted(family_stats.items()):
        family_scores = stats["scores"]
        avg = round(sum(family_scores) / len(family_scores), 1) if family_scores else 0.0
        low = min(family_scores) if family_scores else 0.0
        lines.append(f"| {family} | {stats['cases']} | {stats['passed']} | {avg:.1f} | {low:.1f} |")

    worst = sorted(results, key=lambda r: r.best_score)[:5]
    lines.extend(["", "## Worst Cases", "", "| Case | Family | Best score | Failure |", "|---|---|---:|---|"])
    for r in worst:
        best_attempt = best_attempts[r.case.case_id]
        failure = (best_attempt.failure or best_attempt.model_error) if best_attempt else None
        lines.append(f"| `{r.case.case_id}` | {r.case.family} | {r.best_score:.1f} | {failure or ''} |")

    failure_counts: dict[str, int] = {}
    for r in results:
        for attempt in r.attempts:
            reason = attempt.failure or attempt.model_error
            if not reason:
                continue
            failure_counts[reason] = failure_counts.get(reason, 0) + 1

    lines.extend(["", "## Recurring Failures", ""])
    if failure_counts:
        for reason, count in sorted(failure_counts.items(), key=lambda item: (-item[1], item[0])):
            lines.append(f"- {count}x {reason}")
    else:
        lines.append("- None")

    lines.extend(
        [
            "",
            "## Case Details",
            "",
            "| Case | Reference | Selected template | Validator | Corpus score | Best corpus reference |",
            "|---|---|---|---:|---:|---|",
        ]
    )
    for r in results:
        best_attempt = best_attempts[r.case.case_id]
        selected = Path(r.case.selected_template).name
        reference = Path(r.case.reference).name
        best_ref = Path(best_attempt.best_corpus_reference).name if best_attempt and best_attempt.best_corpus_reference else ""
        validator = (
            f"{best_attempt.validate_errors} errors / {best_attempt.validate_warnings} warnings"
            if best_attempt
            else ""
        )
        corpus_score = best_attempt.corpus_score if best_attempt and best_attempt.corpus_score is not None else 0.0
        lines.append(
            f"| `{r.case.case_id}` | `{reference}` | `{selected}` | {validator} | {corpus_score:.1f} | `{best_ref}` |"
        )

    lines.extend(
        [
            "",
            "## Suggested Improvement Review",
            "",
            "- Inspect failed case `result.json` files for repeated validator errors.",
            "- Compare low-scoring candidates with `compare.py <reference> <candidate>`.",
            "- Convert recurring diffs into `SKILL.md`, selector, validator, or autofix updates.",
        ]
    )
    (run_dir / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def cmd_inventory(args: argparse.Namespace) -> int:
    refs = collect_references(default_reference_inputs(args))
    rows = [{"path": str(p), "family": family_for(p)} for p in refs]
    if args.json:
        print(json.dumps(rows, indent=2))
    else:
        print(f"references: {len(refs)}")
        for row in rows:
            print(f"{row['family']:8s} {row['path']}")
    return 0


def cmd_describe(args: argparse.Namespace) -> int:
    refs = collect_references(default_reference_inputs(args))
    cases = build_cases(refs, args.limit)
    if args.json:
        print(json.dumps([asdict(c) for c in cases], indent=2))
    else:
        for case in cases:
            print(f"{case.case_id}")
            print(f"  reference: {case.reference}")
            print(f"  selected : {case.selected_template} ({case.selected_template_score:.1f})")
            print(f"  prompt   : {case.description}")
    return 0


def cmd_dry_run(args: argparse.Namespace) -> int:
    refs = collect_references(default_reference_inputs(args))
    cases = build_cases(refs, args.limit)
    print(f"dry-run cases: {len(cases)}")
    print(f"generator    : {args.generator}")
    if args.generator == "ollama":
        print(f"model        : {args.model}")
    for case in cases:
        print(f"- {case.case_id}: {case.title}")
        print(f"  target  : {case.reference}")
        print(f"  template: {case.selected_template}")
    return 0


def cmd_generate(args: argparse.Namespace) -> int:
    refs = collect_references(default_reference_inputs(args))
    cases = build_cases(refs, args.limit)
    run_dir, results = run_cases(cases, args, do_score=False)
    print(f"generated {len(results)} case(s) under {run_dir}")
    return 0 if all(r.passed for r in results) else 1


def cmd_score(args: argparse.Namespace) -> int:
    if not args.candidate.exists():
        print(f"{args.candidate}: not found", file=sys.stderr)
        return 2
    refs = collect_references(default_reference_inputs(args))
    validate_rc, validate_errors, validate_warnings, _ = validate_candidate(args.candidate)
    corpus_score, best_ref = best_corpus_score(args.candidate, refs)
    target_score = score_pair(args.target, args.candidate) if args.target else None
    out = {
        "candidate": str(args.candidate),
        "validate_rc": validate_rc,
        "validate_errors": validate_errors,
        "validate_warnings": validate_warnings,
        "corpus_score": corpus_score,
        "best_corpus_reference": best_ref,
        "target_score": target_score,
        "passed": validate_errors == 0 and corpus_score >= args.min_score,
    }
    if args.json:
        print(json.dumps(out, indent=2))
    else:
        print(f"candidate    : {args.candidate}")
        print(f"validate     : errors={validate_errors} warnings={validate_warnings}")
        if target_score is not None:
            print(f"target score : {target_score:.1f}")
        print(f"corpus score : {corpus_score:.1f}")
        print(f"best ref     : {best_ref}")
        print(f"passed       : {out['passed']}")
    return 0 if out["passed"] else 1


def cmd_run(args: argparse.Namespace) -> int:
    refs = collect_references(default_reference_inputs(args))
    cases = build_cases(refs, args.limit)
    started = time.time()
    run_dir, results = run_cases(cases, args, do_score=True)
    elapsed = time.time() - started
    passed = sum(1 for r in results if r.passed)
    print(f"run dir : {run_dir}")
    print(f"cases   : {len(results)}")
    print(f"passed  : {passed}")
    print(f"elapsed : {elapsed:.1f}s")
    print(f"report  : {run_dir / 'report.md'}")
    return 0 if passed == len(results) else 1


def add_common_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--references", type=Path, action="append", default=None, help="reference .drawio file or directory")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--json", action="store_true")


def add_generation_args(parser: argparse.ArgumentParser) -> None:
    add_common_args(parser)
    parser.add_argument("--generator", choices=("baseline", "ollama"), default="baseline")
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--max-attempts", type=int, default=1)
    parser.add_argument("--timeout-seconds", type=int, default=DEFAULT_TIMEOUT_SECONDS)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--min-score", type=float, default=90.0)
    parser.add_argument("--continue-on-error", action="store_true")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("inventory")
    add_common_args(p)
    p.set_defaults(func=cmd_inventory)

    p = sub.add_parser("describe")
    add_common_args(p)
    p.set_defaults(func=cmd_describe)

    p = sub.add_parser("dry-run")
    add_generation_args(p)
    p.set_defaults(func=cmd_dry_run)

    p = sub.add_parser("generate")
    add_generation_args(p)
    p.set_defaults(func=cmd_generate)

    p = sub.add_parser("score")
    p.add_argument("candidate", type=Path)
    p.add_argument("--target", type=Path)
    p.add_argument("--min-score", type=float, default=90.0)
    add_common_args(p)
    p.set_defaults(func=cmd_score)

    p = sub.add_parser("run")
    add_generation_args(p)
    p.set_defaults(func=cmd_run)
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
