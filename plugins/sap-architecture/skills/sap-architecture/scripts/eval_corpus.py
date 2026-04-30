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
import difflib
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
EXPECTED_MODEL_KEYS = {"title", "subtitle", "services", "flow_steps", "style_risks", "template_replacements"}
RESERVED_REPLACEMENT_LABELS = {
    "access",
    "authentication",
    "authorization",
    "data flow",
    "deployment",
    "legend",
    "mutual trust",
    "trust",
}


@dataclass
class EvalCase:
    case_id: str
    reference: str
    family: str
    title: str
    description: str
    selected_template: str
    selected_template_score: float
    selected_template_is_target: bool = False


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
    pass_score: float | None = None
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


def desired_label_hints(description: str, limit: int = 30) -> list[str]:
    """Extract service/label-like hints from a natural-language request."""
    hints: list[str] = []
    match = re.search(r"Visible diagram labels and scenario hints:\s*(.*?)\.\s*Preserve", description)
    if match:
        chunks = re.split(r"\s*;\s*", match.group(1))
    else:
        chunks = re.split(r"\s*(?:;|,|→|->)\s*", description)
    for chunk in chunks:
        label = clean_text(chunk.strip(" ."))
        if not label or len(label) < 3 or len(label) > 100:
            continue
        if label.lower() in {"create", "diagram", "architecture", "sap", "btp"}:
            continue
        if label not in hints:
            hints.append(label)
        if len(hints) >= limit:
            break
    return hints


def same_path(a: Path, b: Path) -> bool:
    try:
        return a.resolve() == b.resolve()
    except OSError:
        return str(a) == str(b)


def select_template(description: str, references: list[Path]) -> tuple[Path, float]:
    ranked = sorted((select_reference_score(p, description) for p in references), key=lambda c: (-c.score, c.path))
    if not ranked:
        raise ValueError("no references available for template selection")
    return Path(ranked[0].path), ranked[0].score


def build_cases(references: list[Path], limit: int | None = None, exclude_target_template: bool = False) -> list[EvalCase]:
    cases: list[EvalCase] = []
    selector_refs = collect_references([DEFAULT_REFERENCE_DIR])
    for ref in references[: limit or None]:
        title, description = build_description(ref)
        selector_pool = [p for p in selector_refs if not same_path(p, ref)] if exclude_target_template else selector_refs
        selected, selected_score = select_template(description, selector_pool)
        cases.append(
            EvalCase(
                case_id=case_id_for(ref),
                reference=str(ref),
                family=family_for(ref),
                title=title,
                description=description,
                selected_template=str(selected),
                selected_template_score=selected_score,
                selected_template_is_target=same_path(selected, ref),
            )
        )
    return cases


def build_case_from_description(description: str, references: list[Path], title: str | None = None) -> EvalCase:
    selected, selected_score = select_template(description, references)
    title_hints = desired_label_hints(description, limit=1)
    case_title = title or (title_hints[0] if title_hints else "Generated SAP architecture")
    return EvalCase(
        case_id=case_id_for(selected),
        reference=str(selected),
        family=family_for(selected),
        title=case_title,
        description=clean_text(description),
        selected_template=str(selected),
        selected_template_score=selected_score,
        selected_template_is_target=True,
    )


def run_id() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")


def prompt_for_ollama(case: EvalCase) -> str:
    template_labels = "; ".join(visible_drawio_labels(Path(case.selected_template), limit=900)[:30])
    desired_labels = "; ".join(desired_label_hints(case.description))
    return f"""You are helping test an SAP Architecture Center draw.io generation skill.

Return JSON only. Do not return XML. Do not use markdown fences.

Create a concise generation plan for this request:
{case.description}

Use the selected SAP template as the base, not a blank canvas:
{case.selected_template}

Selected template visible labels:
{template_labels}

Desired scenario labels and service hints:
{desired_labels}

Available local SAP starter-kit assets:
- extract_icon.py for BTP service icons
- extract_asset.py for generic icons, connector presets, area/default shapes, number markers, SAP brand names, text elements, and annotation/interface pills

Avoid these visual risks:
- generic draw.io colors such as #dae8fc, #d5e8d4, #f8cecc, or #fff2cc
- hand-authored arrows when a connector preset exists
- external image URLs
- clipped labels or oversized text inside service cards
- replacing SAP grey-circle service icons with blank mxgraph stencils
- mixing L0/L1/L2 abstraction levels in one diagram
- rewriting legend entries such as Access, Authentication, Authorization, Trust, or Deployment unless the user explicitly changes the notation

Use these keys:
title: short diagram title
subtitle: one sentence subtitle
services: array of important SAP or external services
flow_steps: array of numbered flow step labels. Include protocols or semantics where useful, for example OAuth, OIDC, HTTPS, Principal Propagation, event, trust, authentication, or authorization.
style_risks: array of visual risks to avoid
template_replacements: array of objects with "from" and "to" label strings for adapting the selected template. Use exact "from" labels from the selected template visible labels. Prefer replacing the title, subtitle, zone headings, and service-card labels. Keep labels short enough to fit the original box.
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


def candidate_label_targets(root: ET.Element) -> list[tuple[ET.Element, str, str]]:
    targets: list[tuple[ET.Element, str, str]] = []
    seen: set[tuple[int, str]] = set()
    for elem in root.iter():
        for attr in ("name", "label", "value"):
            raw = elem.get(attr)
            if not raw:
                continue
            if elem.tag == "mxCell" and attr != "value":
                continue
            label = clean_text(raw)
            if not label or re.fullmatch(r"[0-9.]+", label):
                continue
            if len(label) < 3 or len(label) > 120:
                continue
            key = (id(elem), attr)
            if key in seen:
                continue
            seen.add(key)
            targets.append((elem, attr, label))
    return targets


def is_reserved_replacement_source(label: str) -> bool:
    clean = clean_text(label).lower()
    return clean in RESERVED_REPLACEMENT_LABELS or clean.startswith("diagram level:")


def is_safe_unguarded_replacement(src: str, dst: str, preferred_targets: set[str]) -> bool:
    """Avoid unguarded semantic drift when no target reference is available."""
    src_clean = clean_text(src)
    dst_clean = clean_text(dst)
    if dst_clean in preferred_targets:
        return True
    similarity = difflib.SequenceMatcher(None, src_clean.lower(), dst_clean.lower()).ratio()
    return similarity >= 0.78


def write_tree(path: Path, tree: ET.ElementTree) -> None:
    tree.write(path, encoding="unicode")


def apply_model_plan(candidate_path: Path, model_json: str, target_path: Path | None = None) -> dict[str, Any]:
    """Apply conservative label changes from the Ollama planning JSON.

    This is not full diagram synthesis. It makes the template-copy candidate
    reflect the target scenario labels better while preserving SAP geometry,
    colors, icons, and connector styles from the selected reference.
    """
    try:
        plan = json.loads(model_json)
    except json.JSONDecodeError as exc:
        return {"applied": 0, "error": f"invalid model JSON: {exc}"}

    try:
        tree = ET.parse(candidate_path)
    except ET.ParseError as exc:
        return {"applied": 0, "error": f"candidate XML parse error: {exc}"}

    root = tree.getroot()
    label_targets = candidate_label_targets(root)
    applied: list[dict[str, str]] = []
    rejected: list[dict[str, Any]] = []
    before_score: float | None = score_pair(target_path, candidate_path) if target_path else None
    best_score = before_score or 0.0
    preferred_targets = {
        clean_text(str(plan.get("title", ""))),
        *[
            clean_text(str(service))
            for service in plan.get("services", [])
            if isinstance(service, str)
        ],
    }
    preferred_targets = {target for target in preferred_targets if target}

    replacements: list[tuple[str, str]] = []
    for item in plan.get("template_replacements", []) if isinstance(plan.get("template_replacements"), list) else []:
        if not isinstance(item, dict):
            continue
        src = clean_text(str(item.get("from", "")))
        dst = clean_text(str(item.get("to", "")))
        if src and dst and src != dst and len(dst) <= 120 and not is_reserved_replacement_source(src):
            replacements.append((src, dst))

    for src, dst in replacements:
        for elem, attr, label in label_targets:
            if label == src:
                previous = elem.get(attr) or ""
                elem.set(attr, dst)
                if target_path:
                    write_tree(candidate_path, tree)
                    new_score = score_pair(target_path, candidate_path)
                    if new_score + 0.05 >= best_score:
                        applied.append({"from": src, "to": dst, "target_score": f"{new_score:.1f}"})
                        best_score = new_score
                    else:
                        elem.set(attr, previous)
                        write_tree(candidate_path, tree)
                        rejected.append(
                            {
                                "from": src,
                                "to": dst,
                                "candidate_score": f"{new_score:.1f}",
                                "kept_score": f"{best_score:.1f}",
                            }
                        )
                else:
                    if is_safe_unguarded_replacement(src, dst, preferred_targets):
                        elem.set(attr, dst)
                        applied.append({"from": src, "to": dst})
                    else:
                        elem.set(attr, previous)
                        rejected.append(
                            {
                                "from": src,
                                "to": dst,
                                "reason": "unguarded semantic drift risk",
                            }
                        )
                break

    if applied and not target_path:
        write_tree(candidate_path, tree)
    return {
        "applied": len(applied),
        "rejected": len(rejected),
        "before_target_score": before_score,
        "after_target_score": best_score if target_path else None,
        "changes": applied[:20],
        "rejected_changes": rejected[:20],
    }


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


def compare_payload(reference: Path, candidate: Path) -> dict[str, Any]:
    ref = fingerprint(reference)
    cand = fingerprint(candidate)
    result = compare(ref, cand)
    out: dict[str, Any] = {
        "score": result.score,
        "breakdown": result.breakdown,
        "diffs": result.diffs,
        "reference": asdict(ref),
        "candidate": asdict(cand),
    }
    for fp_dict in (out["reference"], out["candidate"]):
        for key in ("palette", "fonts", "stroke_widths", "shapes", "label_tokens"):
            fp_dict[key] = sorted(fp_dict[key])
    return out


def pass_score_for(pass_mode: str, target_score: float | None, corpus_score: float | None) -> float:
    target = target_score or 0.0
    corpus = corpus_score or 0.0
    if pass_mode == "target":
        return target
    if pass_mode == "corpus":
        return corpus
    if pass_mode == "both":
        return min(target, corpus)
    raise ValueError(f"unknown pass mode {pass_mode!r}")


def run_one_attempt(
    case: EvalCase,
    attempt: int,
    case_dir: Path,
    generator: str,
    model: str,
    timeout_seconds: int,
    min_score: float,
    pass_mode: str,
    corpus_refs: list[Path],
    do_score: bool,
    apply_model_plan_enabled: bool,
) -> AttemptResult:
    attempt_dir = case_dir / f"attempt-{attempt}"
    attempt_dir.mkdir(parents=True, exist_ok=True)
    result = AttemptResult(attempt=attempt)
    model_json_text: str | None = None

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
            model_json_text = model_json
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
    if generator == "ollama" and apply_model_plan_enabled and model_json_text:
        apply_result = apply_model_plan(candidate, model_json_text, Path(case.reference) if do_score else None)
        write_json(attempt_dir / "model-plan-application.json", apply_result)
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
    write_json(attempt_dir / "target-compare.json", compare_payload(Path(case.reference), candidate))
    if result.best_corpus_reference:
        write_json(attempt_dir / "best-corpus-compare.json", compare_payload(Path(result.best_corpus_reference), candidate))
    result.pass_score = pass_score_for(pass_mode, result.target_score, result.corpus_score)
    result.passed = result.validate_errors == 0 and result.pass_score >= min_score
    if not result.passed:
        result.failure = (
            f"validator_errors={result.validate_errors}, pass_mode={pass_mode}, "
            f"pass_score={result.pass_score:.1f}, target_score={result.target_score:.1f}, "
            f"corpus_score={result.corpus_score:.1f}"
        )
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
                pass_mode=args.pass_mode,
                corpus_refs=corpus_refs,
                do_score=do_score,
                apply_model_plan_enabled=args.apply_model_plan,
            )
            case_result.attempts.append(attempt_result)
            if attempt_result.pass_score is not None:
                case_result.best_score = max(case_result.best_score, attempt_result.pass_score)
            if attempt_result.passed:
                case_result.passed = True
                break
            if attempt_result.failure and not args.continue_on_error and attempt == args.max_attempts:
                break
        write_json(case_dir / "result.json", asdict(case_result))
        results.append(case_result)
        if not case_result.passed and not args.continue_on_error:
            break

    write_reports(run_dir, results, args.min_score, args.pass_mode)
    return run_dir, results


def write_reports(run_dir: Path, results: list[CaseResult], min_score: float, pass_mode: str) -> None:
    passed = sum(1 for r in results if r.passed)
    scores = [r.best_score for r in results if r.best_score]
    best_attempts = {
        r.case.case_id: max(r.attempts, key=lambda a: a.pass_score or 0.0) if r.attempts else None
        for r in results
    }
    target_scores = [
        a.target_score
        for a in best_attempts.values()
        if a is not None and a.target_score is not None
    ]
    corpus_scores = [
        a.corpus_score
        for a in best_attempts.values()
        if a is not None and a.corpus_score is not None
    ]
    summary = {
        "run_dir": str(run_dir),
        "case_count": len(results),
        "passed": passed,
        "failed": len(results) - passed,
        "min_score": min_score,
        "pass_mode": pass_mode,
        "average_best_score": round(sum(scores) / len(scores), 1) if scores else 0.0,
        "average_target_score": round(sum(target_scores) / len(target_scores), 1) if target_scores else 0.0,
        "average_corpus_score": round(sum(corpus_scores) / len(corpus_scores), 1) if corpus_scores else 0.0,
        "selected_target_template_count": sum(1 for r in results if r.case.selected_template_is_target),
        "results": [asdict(r) for r in results],
    }
    write_json(run_dir / "summary.json", summary)

    lines = [
        "# SAP Architecture Evaluation Report",
        "",
        f"- Cases: {len(results)}",
        f"- Passed: {passed}",
        f"- Failed: {len(results) - passed}",
        f"- Pass mode: {pass_mode}",
        f"- Minimum pass score: {min_score}",
        f"- Average pass score: {summary['average_best_score']}",
        f"- Average target score: {summary['average_target_score']}",
        f"- Average corpus score: {summary['average_corpus_score']}",
        f"- Selected target template count: {summary['selected_target_template_count']}",
        "",
        "| Case | Family | Passed | Pass score | Target score | Corpus score | Target template | Candidate |",
        "|---|---|---:|---:|---:|---:|---:|---|",
    ]
    for r in results:
        best_attempt = best_attempts[r.case.case_id]
        target = best_attempt.target_score if best_attempt and best_attempt.target_score is not None else 0.0
        corpus = best_attempt.corpus_score if best_attempt and best_attempt.corpus_score is not None else 0.0
        candidate = best_attempt.candidate if best_attempt and best_attempt.candidate else ""
        lines.append(
            f"| `{r.case.case_id}` | {r.case.family} | {str(r.passed).lower()} | "
            f"{r.best_score:.1f} | {target:.1f} | {corpus:.1f} | "
            f"{str(r.case.selected_template_is_target).lower()} | `{candidate}` |"
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
            "| Case | Reference | Selected template | Target template | Validator | Target score | Corpus score | Best corpus reference |",
            "|---|---|---|---:|---:|---:|---:|---|",
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
        target_score = best_attempt.target_score if best_attempt and best_attempt.target_score is not None else 0.0
        lines.append(
            f"| `{r.case.case_id}` | `{reference}` | `{selected}` | "
            f"{str(r.case.selected_template_is_target).lower()} | {validator} | "
            f"{target_score:.1f} | {corpus_score:.1f} | `{best_ref}` |"
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


def cmd_create(args: argparse.Namespace) -> int:
    description = " ".join(args.description).strip()
    if not description:
        print("description required", file=sys.stderr)
        return 2

    refs = collect_references(default_reference_inputs(args))
    if args.exclude_target_template and args.target:
        refs = [ref for ref in refs if not same_path(ref, args.target)]
    if not refs:
        print("no reference templates found", file=sys.stderr)
        return 2

    case = build_case_from_description(description, refs, args.title)
    rid = run_id()
    run_dir = args.out_dir / rid
    attempt_dir = run_dir / "create"
    attempt_dir.mkdir(parents=True, exist_ok=True)

    candidate = args.out_file or (run_dir / "candidate.drawio")
    candidate.parent.mkdir(parents=True, exist_ok=True)
    make_candidate_from_template(case, candidate)

    model_json_text: str | None = None
    raw_model_output: str | None = None
    model_error: str | None = None
    if args.generator == "ollama":
        try:
            raw_model_output, model_json_text, model_error = call_ollama(case, args.model, args.timeout_seconds)
        except subprocess.TimeoutExpired:
            model_error = f"ollama timed out after {args.timeout_seconds}s"
            raw_model_output = ""
        (attempt_dir / "model-output.txt").write_text(raw_model_output or "", encoding="utf-8")
        if model_json_text:
            (attempt_dir / "model-output.json").write_text(model_json_text, encoding="utf-8")
        if model_error:
            (attempt_dir / "model-error.txt").write_text(model_error, encoding="utf-8")
    elif args.generator != "baseline":
        print(f"unknown generator {args.generator!r}", file=sys.stderr)
        return 2

    if args.generator == "ollama" and args.apply_model_plan and model_json_text:
        write_json(attempt_dir / "model-plan-application.json", apply_model_plan(candidate, model_json_text))

    autofix = run_cli([sys.executable, str(SCRIPT_DIR / "autofix.py"), "--write", str(candidate)])
    (attempt_dir / "autofix.stdout.txt").write_text(autofix.stdout, encoding="utf-8")
    (attempt_dir / "autofix.stderr.txt").write_text(autofix.stderr, encoding="utf-8")

    validate_rc, validate_errors, validate_warnings, validate_error_details = validate_candidate(candidate)
    write_json(attempt_dir / "validate-errors.json", validate_error_details)
    corpus_score, best_ref = best_corpus_score(candidate, collect_references([DEFAULT_REFERENCE_DIR]))
    target_score = score_pair(args.target, candidate) if args.target else None
    if args.target:
        write_json(attempt_dir / "target-compare.json", compare_payload(args.target, candidate))
    if best_ref:
        write_json(attempt_dir / "best-corpus-compare.json", compare_payload(Path(best_ref), candidate))

    summary = {
        "description": description,
        "candidate": str(candidate),
        "selected_template": case.selected_template,
        "selected_template_score": case.selected_template_score,
        "generator": args.generator,
        "model": args.model if args.generator == "ollama" else None,
        "model_error": model_error,
        "autofix_rc": autofix.returncode,
        "validate_rc": validate_rc,
        "validate_errors": validate_errors,
        "validate_warnings": validate_warnings,
        "corpus_score": corpus_score,
        "best_corpus_reference": best_ref,
        "target": str(args.target) if args.target else None,
        "target_score": target_score,
    }
    write_json(run_dir / "create-summary.json", summary)

    if args.json:
        print(json.dumps(summary, indent=2))
    else:
        print(f"run dir          : {run_dir}")
        print(f"candidate        : {candidate}")
        print(f"selected template: {case.selected_template} ({case.selected_template_score:.1f})")
        print(f"validate         : errors={validate_errors} warnings={validate_warnings}")
        print(f"corpus score     : {corpus_score:.1f}")
        print(f"best corpus ref  : {best_ref}")
        if target_score is not None:
            print(f"target score     : {target_score:.1f}")
        print(f"summary          : {run_dir / 'create-summary.json'}")
    return 0 if validate_errors == 0 else 1


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
    cases = build_cases(refs, args.limit, args.exclude_target_template)
    print(f"dry-run cases: {len(cases)}")
    print(f"generator    : {args.generator}")
    print(f"pass mode    : {args.pass_mode}")
    print(f"exclude target template: {str(args.exclude_target_template).lower()}")
    print(f"apply model plan: {str(args.apply_model_plan).lower()}")
    if args.generator == "ollama":
        print(f"model        : {args.model}")
    for case in cases:
        print(f"- {case.case_id}: {case.title}")
        print(f"  target  : {case.reference}")
        print(f"  template: {case.selected_template} (target={str(case.selected_template_is_target).lower()})")
    return 0


def cmd_generate(args: argparse.Namespace) -> int:
    refs = collect_references(default_reference_inputs(args))
    cases = build_cases(refs, args.limit, args.exclude_target_template)
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
    pass_mode = args.pass_mode or ("target" if args.target else "corpus")
    pass_score = pass_score_for(pass_mode, target_score, corpus_score)
    out = {
        "candidate": str(args.candidate),
        "validate_rc": validate_rc,
        "validate_errors": validate_errors,
        "validate_warnings": validate_warnings,
        "corpus_score": corpus_score,
        "best_corpus_reference": best_ref,
        "target_score": target_score,
        "pass_mode": pass_mode,
        "pass_score": pass_score,
        "passed": validate_errors == 0 and pass_score >= args.min_score,
    }
    if args.json:
        print(json.dumps(out, indent=2))
    else:
        print(f"candidate    : {args.candidate}")
        print(f"validate     : errors={validate_errors} warnings={validate_warnings}")
        if target_score is not None:
            print(f"target score : {target_score:.1f}")
        print(f"corpus score : {corpus_score:.1f}")
        print(f"pass mode    : {pass_mode}")
        print(f"pass score   : {pass_score:.1f}")
        print(f"best ref     : {best_ref}")
        print(f"passed       : {out['passed']}")
    return 0 if out["passed"] else 1


def cmd_run(args: argparse.Namespace) -> int:
    refs = collect_references(default_reference_inputs(args))
    cases = build_cases(refs, args.limit, args.exclude_target_template)
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
    parser.add_argument("--pass-mode", choices=("target", "corpus", "both"), default="target")
    parser.add_argument("--exclude-target-template", action="store_true")
    parser.add_argument("--apply-model-plan", action="store_true", help="For Ollama runs, apply conservative label replacements from model JSON")
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

    p = sub.add_parser("create")
    add_generation_args(p)
    p.add_argument("description", nargs="*", help="natural-language diagram description")
    p.add_argument("--title")
    p.add_argument("--out-file", type=Path)
    p.add_argument("--target", type=Path, help="optional reference .drawio to compare after creation")
    p.set_defaults(func=cmd_create)

    p = sub.add_parser("score")
    p.add_argument("candidate", type=Path)
    p.add_argument("--target", type=Path)
    p.add_argument("--min-score", type=float, default=90.0)
    p.add_argument("--pass-mode", choices=("target", "corpus", "both"))
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
