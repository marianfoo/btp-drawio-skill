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
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from compare import compare, fingerprint
from select_reference import (
    explicit_metadata_title,
    metadata_search_text,
    score as select_reference_score,
    template_metadata,
    tokens as selector_tokens,
)

SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_DIR = SCRIPT_DIR.parent
DEFAULT_REFERENCE_DIR = SKILL_DIR / "assets" / "reference-examples"
DEFAULT_OUT_DIR = Path(".cache") / "sap-architecture-eval"
DEFAULT_MODEL = "qwen3.6:35b-a3b-nvfp4"
DEFAULT_OLLAMA_ENDPOINT = "http://127.0.0.1:11434"
DEFAULT_TIMEOUT_SECONDS = 600
VISIBLE_TEXT_LIMIT = 1800
ANSI_RE = re.compile(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")
CONTROL_RE = re.compile(r"[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]")
EXPECTED_MODEL_KEYS = {"title", "subtitle", "services", "flow_steps", "style_risks", "template_replacements"}
GENERATION_PLAN_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "title": {"type": "string"},
        "subtitle": {"type": "string"},
        "services": {"type": "array", "items": {"type": "string"}},
        "flow_steps": {"type": "array", "items": {"type": "string"}},
        "style_risks": {"type": "array", "items": {"type": "string"}},
        "template_replacements": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "from": {"type": "string"},
                    "to": {"type": "string"},
                },
                "required": ["from", "to"],
            },
        },
    },
    "required": ["title", "subtitle", "services", "flow_steps", "style_risks", "template_replacements"],
}
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
GENERIC_TITLES = {
    "generic",
    "btp service",
    "btp services",
    "l2/l3 diagram",
    "multi-cloud",
    "network",
    "page-1",
    "page-2",
    "page-3",
    "sap btp",
    "post",
    "pre",
    "without logo",
    "without logos",
}
ENCODED_XML_RE = re.compile(r"%3CmxGraphModel|%3Croot%3E|mxGraphModel|mxCell|data:image|PHN2Zy", re.I)


@dataclass
class EvalCase:
    case_id: str
    reference: str
    family: str
    title: str
    description: str
    selected_template: str
    selected_template_score: float
    selected_template_target_score: float | None = None
    selected_template_is_target: bool = False
    selector_candidates: list[dict[str, Any]] = field(default_factory=list)
    style_neighbor_hints: list[dict[str, Any]] = field(default_factory=list)


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
    feedback: str | None = None


@dataclass
class CaseResult:
    case: EvalCase
    attempts: list[AttemptResult] = field(default_factory=list)
    passed: bool = False
    best_score: float = 0.0
    retry_stopped_early: bool = False
    retry_stop_reason: str | None = None


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


_FINGERPRINT_CACHE: dict[str, Any] = {}


def cached_fingerprint(path: Path):
    key = str(path.resolve())
    if key not in _FINGERPRINT_CACHE:
        _FINGERPRINT_CACHE[key] = fingerprint(path)
    return _FINGERPRINT_CACHE[key]


def clean_text(value: str) -> str:
    value = html.unescape(value)
    value = re.sub(r"<br\s*/?>", " ", value, flags=re.I)
    value = re.sub(r"<[^>]+>", " ", value)
    value = re.sub(r"&nbsp;", " ", value)
    value = re.sub(r"\s+", " ", value).strip()
    return value


def is_noise_label(text: str) -> bool:
    stripped = clean_text(text)
    if not stripped:
        return True
    if stripped.lower() in GENERIC_TITLES:
        return True
    if not re.search(r"[A-Za-z]", stripped):
        return True
    if re.fullmatch(r"[\"'`> <]+", stripped):
        return True
    if re.fullmatch(r"\d{5,8}", stripped):
        return True
    if ENCODED_XML_RE.search(stripped):
        return True
    # Encoded SVG/XML payloads can survive as plain percent-encoded text. They
    # are useful for rendering but disastrous as natural-language prompts.
    if stripped.count("%") > 8 and len(stripped) > 80:
        return True
    if len(stripped) > 260:
        return True
    return False


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
            if is_noise_label(text) or text in labels:
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
    if path.name.startswith("ext_"):
        return _ext_family_for(path)
    return "unknown"


_EXT_FAMILY_MAP = {
    # Maps filename stem → family tag for templates from
    # SAP/sap-btp-reference-architectures bundled under the ext_ prefix.
    "ext_MasterDataIntegration": "ext-mdi",
    "ext_BusinessToGovernment": "ext-b2g",
    "ext_EventsToBusinessActions": "ext-events",
    "ext_FederatedML_v2": "RA0003",
    "ext_MultiRegionResiliency_v2": "RA0002",
    "ext_GenAI_RAG_v2": "RA0005",
    "ext_HyperscalerDatasphere": "RA0004",
    "ext_CloudLeadingAuthn": "RA0019",
}


def _ext_family_for(path: Path) -> str:
    return _EXT_FAMILY_MAP.get(path.stem, "ext")


def title_from_stem(path: Path) -> str:
    stem = re.sub(r"^(ac_|btp_)", "", path.stem, flags=re.I)
    stem = stem.replace("_", " ").replace("-", " ")
    stem = re.sub(r"\bRA(\d{4})\b", r"RA\1", stem, flags=re.I)
    stem = re.sub(r"\s+", " ", stem).strip()
    return stem


def title_for(path: Path, labels: list[str]) -> str:
    metadata_title = explicit_metadata_title(path)
    if metadata_title:
        return metadata_title
    # External SAP reference repositories often have generic first labels such
    # as "Subaccount" or "Network". Their filenames are usually better scenario
    # titles than the first visible mxCell label.
    if not re.match(r"^(ac_|btp_)", path.name, flags=re.I):
        return title_from_stem(path)
    if labels:
        first = labels[0]
        if 4 <= len(first) <= 140 and first.lower() not in GENERIC_TITLES:
            return first
    return title_from_stem(path)


def case_id_for(path: Path) -> str:
    digest = hashlib.sha1(str(path).encode("utf-8")).hexdigest()[:8]
    stem = re.sub(r"[^A-Za-z0-9]+", "-", path.stem).strip("-").lower()[:48]
    return f"{stem}-{digest}"


def style_neighbors_for(path: Path, candidates: list[Path], limit: int = 3) -> list[dict[str, Any]]:
    ref_fp = cached_fingerprint(path)
    rows: list[dict[str, Any]] = []
    for candidate in candidates:
        if same_path(path, candidate):
            continue
        result = compare(ref_fp, cached_fingerprint(candidate))
        rows.append({"path": str(candidate), "name": candidate.name, "score": result.score})
    rows.sort(key=lambda row: (-float(row["score"]), str(row["name"])))
    return rows[:limit]


def fingerprint_score(reference: Path, candidate: Path) -> float:
    return compare(cached_fingerprint(reference), cached_fingerprint(candidate)).score


def build_description(path: Path, style_neighbor_hints: list[dict[str, Any]] | None = None) -> tuple[str, str]:
    labels = visible_drawio_labels(path)
    title = title_for(path, labels)
    md = nearby_markdown_text(path)
    hints = "; ".join(labels[:18])
    metadata = template_metadata(path)
    meta_text = metadata_search_text(path, metadata)
    meta_tokens = sorted(selector_tokens(meta_text))[:24]
    parts = [
        f"Create an SAP Architecture Center style diagram for: {title}.",
        f"Scenario source file: {title_from_stem(path)}.",
        f"Reference family: {family_for(path)}.",
    ]
    if metadata.get("domain"):
        parts.append(f"Scenario domain: {metadata['domain']}.")
    if metadata.get("level"):
        parts.append(f"Diagram level: {str(metadata['level']).upper()}.")
    if metadata.get("aliases"):
        parts.append("Scenario aliases: " + "; ".join(str(x) for x in metadata["aliases"][:6]) + ".")
    if meta_tokens:
        parts.append("Scenario tags: " + ", ".join(meta_tokens) + ".")
    if style_neighbor_hints:
        parts.append(f"Primary SAP visual fallback template: {style_neighbor_hints[0]['name']}.")
        parts.append(
            "Nearest SAP visual fallback templates from corpus fingerprinting: "
            + "; ".join(f"{item['name']} ({item['score']:.1f})" for item in style_neighbor_hints)
            + "."
        )
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


def ranked_templates(description: str, references: list[Path], top: int = 5) -> list:
    return sorted((select_reference_score(p, description) for p in references), key=lambda c: (-c.score, c.path))[:top]


def select_template(description: str, references: list[Path]) -> tuple[Path, float, list[dict[str, Any]]]:
    ranked = ranked_templates(description, references, top=5)
    if not ranked:
        raise ValueError("no references available for template selection")
    candidates = [
        {
            "path": c.path,
            "score": c.score,
            "reasons": c.reasons[:5],
            "token_hits": c.token_hits,
            "metadata_title": c.metadata_title,
            "metadata_tags": c.metadata_tags,
        }
        for c in ranked
    ]
    return Path(ranked[0].path), ranked[0].score, candidates


def build_cases(
    references: list[Path],
    limit: int | None = None,
    exclude_target_template: bool = False,
    style_neighbor_hints_enabled: bool = True,
) -> list[EvalCase]:
    cases: list[EvalCase] = []
    selector_refs = collect_references([DEFAULT_REFERENCE_DIR])
    for ref in references[: limit or None]:
        selector_pool = [p for p in selector_refs if not same_path(p, ref)] if exclude_target_template else selector_refs
        style_neighbor_hints = (
            style_neighbors_for(ref, selector_pool)
            if exclude_target_template and style_neighbor_hints_enabled
            else []
        )
        title, description = build_description(ref, style_neighbor_hints)
        selected, selected_score, selector_candidates = select_template(description, selector_pool)
        selected_template_target_score = fingerprint_score(ref, selected)
        cases.append(
            EvalCase(
                case_id=case_id_for(ref),
                reference=str(ref),
                family=family_for(ref),
                title=title,
                description=description,
                selected_template=str(selected),
                selected_template_score=selected_score,
                selected_template_target_score=selected_template_target_score,
                selected_template_is_target=same_path(selected, ref),
                selector_candidates=selector_candidates,
                style_neighbor_hints=style_neighbor_hints,
            )
        )
    return cases


def best_attempt_dict(result: dict[str, Any]) -> dict[str, Any] | None:
    attempts = result.get("attempts") or []
    if not attempts:
        return None
    return max(attempts, key=lambda a: a.get("pass_score") or 0.0)


def classify_result_dict(result: dict[str, Any], min_score: float, retry_margin: float) -> str:
    if result.get("passed"):
        return "passed"
    attempt = best_attempt_dict(result)
    if attempt is None:
        return "not-run"
    if attempt.get("model_error") and attempt.get("pass_score") is None:
        return "model-failure"
    if attempt.get("validate_errors"):
        return "validator-failure"
    if float(result.get("best_score") or 0.0) >= min_score - retry_margin:
        return "near-miss"
    return "ceiling-limited"


def load_run_summary(path: Path) -> dict[str, Any]:
    summary = path if path.name == "summary.json" else path / "summary.json"
    if not summary.exists():
        raise ValueError(f"{summary}: run summary not found")
    return json.loads(summary.read_text(encoding="utf-8"))


def selected_case_ids_from_run(args: argparse.Namespace) -> set[str] | None:
    classes = set(getattr(args, "case_class", None) or [])
    run_path = getattr(args, "from_run", None)
    if not run_path:
        if classes:
            raise ValueError("--case-class requires --from-run")
        return None
    summary = load_run_summary(run_path)
    summary_min_score = summary.get("min_score")
    summary_retry_margin = summary.get("retry_margin")
    min_score = float(summary_min_score if summary_min_score is not None else getattr(args, "min_score", 90.0))
    retry_margin = float(summary_retry_margin if summary_retry_margin is not None else getattr(args, "retry_margin", 8.0))
    selected: set[str] = set()
    for result in summary.get("results", []):
        case_id = result.get("case", {}).get("case_id")
        if not case_id:
            continue
        classification = classify_result_dict(result, min_score, retry_margin)
        failed = classification != "passed"
        if not classes or classification in classes or ("failed" in classes and failed):
            selected.add(case_id)
    return selected


def case_matches_queries(case: EvalCase, queries: list[str]) -> bool:
    haystack = " ".join(
        [
            case.case_id,
            case.family,
            case.title,
            Path(case.reference).name,
        ]
    ).lower()
    return all(query.lower() in haystack for query in queries)


def generation_case_filters_enabled(args: argparse.Namespace) -> bool:
    return bool(getattr(args, "case_id", None) or getattr(args, "case_class", None) or getattr(args, "from_run", None))


def build_generation_cases(args: argparse.Namespace) -> list[EvalCase]:
    refs = collect_references(default_reference_inputs(args))
    prefilter_limit = None if generation_case_filters_enabled(args) else args.limit
    cases = build_cases(refs, prefilter_limit, args.exclude_target_template, not args.no_style_neighbor_hints)

    selected_ids = selected_case_ids_from_run(args)
    if selected_ids is not None:
        cases = [case for case in cases if case.case_id in selected_ids]

    queries = getattr(args, "case_id", None) or []
    if queries:
        cases = [case for case in cases if case_matches_queries(case, queries)]

    if generation_case_filters_enabled(args) and args.limit is not None:
        cases = cases[: args.limit]
    return cases


def build_case_from_description(description: str, references: list[Path], title: str | None = None) -> EvalCase:
    selected, selected_score, selector_candidates = select_template(description, references)
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
        selector_candidates=selector_candidates,
    )


def run_id() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")


def _json_default(obj: Any) -> Any:
    if isinstance(obj, set):
        return sorted(obj)
    if hasattr(obj, "__fspath__"):
        return str(obj)
    raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, indent=2, sort_keys=True, default=_json_default),
        encoding="utf-8",
    )


def prompt_for_ollama(case: EvalCase, feedback: str | None = None) -> str:
    template_labels = "; ".join(visible_drawio_labels(Path(case.selected_template), limit=900)[:30])
    desired_labels = "; ".join(desired_label_hints(case.description))
    feedback_block = ""
    if feedback:
        feedback_block = f"""

Previous attempt feedback:
{feedback}

Use that feedback to improve only the JSON plan. In this harness, the plan can safely replace labels in an SAP template; it cannot redesign geometry from scratch. Prefer exact visible-label replacements that improve SAP terminology and target overlap while preserving the selected template's layout, colors, icon count, connector count, and notation.
"""
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
{feedback_block}

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

Required JSON schema:
{json.dumps(GENERATION_PLAN_SCHEMA, indent=2)}
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


def call_ollama_api(
    prompt: str,
    model: str,
    endpoint: str,
    timeout_seconds: int,
    temperature: float,
) -> tuple[str, str | None, str | None]:
    url = endpoint.rstrip("/") + "/api/generate"
    payload = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "format": GENERATION_PLAN_SCHEMA,
        "think": False,
        "options": {
            "temperature": temperature,
        },
    }
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout_seconds) as resp:
        body = resp.read().decode("utf-8")
    try:
        api_response = json.loads(body)
    except json.JSONDecodeError:
        return body, None, "ollama API returned non-JSON response"
    raw = str(api_response.get("response", "")).strip()
    if not raw:
        raw = json.dumps(api_response, indent=2, sort_keys=True)
    model_json, parse_error = extract_json_object(raw)
    return raw, model_json, parse_error


def call_ollama_cli(prompt: str, model: str, timeout_seconds: int) -> tuple[str, str | None, str | None]:
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


def call_ollama(
    case: EvalCase,
    model: str,
    timeout_seconds: int,
    endpoint: str,
    temperature: float,
    feedback: str | None = None,
) -> tuple[str, str | None, str | None]:
    prompt = prompt_for_ollama(case, feedback)
    try:
        return call_ollama_api(prompt, model, endpoint, timeout_seconds, temperature)
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raw, model_json, model_error = call_ollama_cli(prompt, model, timeout_seconds)
        if model_error:
            model_error = f"ollama API unavailable at {endpoint}: {exc}; CLI fallback failed: {model_error}"
        return raw, model_json, model_error


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


def best_attempt_for(result: CaseResult) -> AttemptResult | None:
    if not result.attempts:
        return None
    return max(result.attempts, key=lambda a: a.pass_score or 0.0)


def score_band(score: float) -> str:
    if score >= 90:
        return "90+"
    if score >= 85:
        return "85-90"
    if score >= 82:
        return "82-85"
    if score >= 80:
        return "80-82"
    if score >= 70:
        return "70-80"
    if score >= 60:
        return "60-70"
    return "<60"


def classify_result(result: CaseResult, min_score: float, retry_margin: float) -> str:
    if result.passed:
        return "passed"
    attempt = best_attempt_for(result)
    if attempt is None:
        return "not-run"
    if attempt.model_error and attempt.pass_score is None:
        return "model-failure"
    if attempt.validate_errors:
        return "validator-failure"
    retry_floor = min_score - retry_margin
    if result.best_score >= retry_floor:
        return "near-miss"
    return "ceiling-limited"


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


def build_retry_feedback(
    case: EvalCase,
    result: AttemptResult,
    target_payload: dict[str, Any] | None,
    apply_result: dict[str, Any] | None,
    min_score: float,
) -> str:
    lines = [
        (
            f"Attempt {result.attempt} scored pass={result.pass_score or 0.0:.1f}, "
            f"target={result.target_score or 0.0:.1f}, corpus={result.corpus_score or 0.0:.1f}; "
            f"required pass score is {min_score:.1f}."
        )
    ]
    if result.validate_errors or result.validate_warnings:
        lines.append(f"Validator: {result.validate_errors} errors, {result.validate_warnings} warnings.")
    if case.selected_template_target_score is not None:
        lines.append(
            f"Selected-template ceiling against target is {case.selected_template_target_score:.1f}; "
            "do not fight the template geometry when that ceiling is low."
        )
    if target_payload:
        breakdown = target_payload.get("breakdown", {})
        weak = [
            f"{key}={value * 100:.0f}%"
            for key, value in sorted(breakdown.items(), key=lambda item: item[1])
            if isinstance(value, (int, float)) and value < 0.95
        ][:6]
        if weak:
            lines.append("Weak target fingerprint dimensions: " + ", ".join(weak) + ".")
        diffs = [str(diff) for diff in target_payload.get("diffs", [])[:5]]
        if diffs:
            lines.append("Target diffs: " + " | ".join(diffs) + ".")
    if apply_result:
        lines.append(
            f"Previous label-plan application: applied={apply_result.get('applied', 0)}, "
            f"rejected={apply_result.get('rejected', 0)}."
        )
        rejected = apply_result.get("rejected_changes") or []
        if rejected:
            examples = []
            for item in rejected[:4]:
                examples.append(f"{item.get('from', '')}->{item.get('to', '')}")
            lines.append("Avoid rejected replacements: " + "; ".join(examples) + ".")
    lines.append(
        "Next attempt: return JSON only; use exact source labels from the selected template; "
        "favor title, subtitle, zone heading, and service-card replacements over legend notation changes."
    )
    return clean_text(" ".join(lines))[:1800]


def run_one_attempt(
    case: EvalCase,
    attempt: int,
    case_dir: Path,
    generator: str,
    model: str,
    ollama_endpoint: str,
    temperature: float,
    timeout_seconds: int,
    min_score: float,
    pass_mode: str,
    corpus_refs: list[Path],
    do_score: bool,
    apply_model_plan_enabled: bool,
    feedback: str | None = None,
) -> AttemptResult:
    attempt_dir = case_dir / f"attempt-{attempt}"
    attempt_dir.mkdir(parents=True, exist_ok=True)
    result = AttemptResult(attempt=attempt)
    model_json_text: str | None = None
    apply_result: dict[str, Any] | None = None

    if generator == "ollama":
        try:
            raw, model_json, model_error = call_ollama(
                case,
                model,
                timeout_seconds,
                ollama_endpoint,
                temperature,
                feedback,
            )
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
    target_payload = compare_payload(Path(case.reference), candidate)
    write_json(attempt_dir / "target-compare.json", target_payload)
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
    result.feedback = build_retry_feedback(case, result, target_payload, apply_result, min_score)
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
        retry_feedback: str | None = None
        for attempt in range(1, args.max_attempts + 1):
            attempt_result = run_one_attempt(
                case=case,
                attempt=attempt,
                case_dir=case_dir,
                generator=args.generator,
                model=args.model,
                ollama_endpoint=args.ollama_endpoint,
                temperature=args.temperature,
                timeout_seconds=args.timeout_seconds,
                min_score=args.min_score,
                pass_mode=args.pass_mode,
                corpus_refs=corpus_refs,
                do_score=do_score,
                apply_model_plan_enabled=args.apply_model_plan,
                feedback=retry_feedback,
            )
            case_result.attempts.append(attempt_result)
            if attempt_result.pass_score is not None:
                case_result.best_score = max(case_result.best_score, attempt_result.pass_score)
            retry_feedback = attempt_result.feedback
            if attempt_result.passed:
                case_result.passed = True
                break
            if args.generator == "baseline":
                if attempt < args.max_attempts:
                    case_result.retry_stopped_early = True
                    case_result.retry_stop_reason = "baseline generator is deterministic"
                break
            if (
                do_score
                and attempt_result.pass_score is not None
                and args.retry_margin >= 0
                and attempt_result.pass_score < args.min_score - args.retry_margin
                and attempt < args.max_attempts
            ):
                case_result.retry_stopped_early = True
                case_result.retry_stop_reason = (
                    f"pass_score={attempt_result.pass_score:.1f} below retry floor "
                    f"{args.min_score - args.retry_margin:.1f}"
                )
                break
            if attempt_result.failure and not args.continue_on_error and attempt == args.max_attempts:
                break
        write_json(case_dir / "result.json", asdict(case_result))
        results.append(case_result)
        if not case_result.passed and not args.continue_on_error:
            break

    write_reports(run_dir, results, args.min_score, args.pass_mode, args.retry_margin)
    return run_dir, results


def write_reports(run_dir: Path, results: list[CaseResult], min_score: float, pass_mode: str, retry_margin: float) -> None:
    passed = sum(1 for r in results if r.passed)
    scores = [r.best_score for r in results if r.best_score]
    best_attempts = {r.case.case_id: best_attempt_for(r) for r in results}
    classifications = {r.case.case_id: classify_result(r, min_score, retry_margin) for r in results}
    score_bands: dict[str, int] = {}
    for r in results:
        band = score_band(r.best_score)
        score_bands[band] = score_bands.get(band, 0) + 1
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
    baseline_scores = [
        r.case.selected_template_target_score
        for r in results
        if r.case.selected_template_target_score is not None
    ]
    summary = {
        "run_dir": str(run_dir),
        "case_count": len(results),
        "passed": passed,
        "failed": len(results) - passed,
        "min_score": min_score,
        "pass_mode": pass_mode,
        "retry_margin": retry_margin,
        "retry_floor": min_score - retry_margin,
        "attempt_count": sum(len(r.attempts) for r in results),
        "average_attempts": round(sum(len(r.attempts) for r in results) / len(results), 2) if results else 0.0,
        "early_stopped_count": sum(1 for r in results if r.retry_stopped_early),
        "near_miss_count": sum(1 for r in results if classifications[r.case.case_id] == "near-miss"),
        "ceiling_limited_count": sum(1 for r in results if classifications[r.case.case_id] == "ceiling-limited"),
        "model_failure_count": sum(1 for r in results if classifications[r.case.case_id] == "model-failure"),
        "validator_failure_count": sum(1 for r in results if classifications[r.case.case_id] == "validator-failure"),
        "score_bands": dict(sorted(score_bands.items())),
        "average_best_score": round(sum(scores) / len(scores), 1) if scores else 0.0,
        "average_target_score": round(sum(target_scores) / len(target_scores), 1) if target_scores else 0.0,
        "average_corpus_score": round(sum(corpus_scores) / len(corpus_scores), 1) if corpus_scores else 0.0,
        "average_selected_template_target_score": round(sum(baseline_scores) / len(baseline_scores), 1) if baseline_scores else 0.0,
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
        f"- Retry floor: {summary['retry_floor']} (`--retry-margin {retry_margin}`)",
        f"- Attempts: {summary['attempt_count']} (average {summary['average_attempts']})",
        f"- Early retry stops: {summary['early_stopped_count']}",
        f"- Near misses: {summary['near_miss_count']}",
        f"- Ceiling-limited cases: {summary['ceiling_limited_count']}",
        f"- Average pass score: {summary['average_best_score']}",
        f"- Average target score: {summary['average_target_score']}",
        f"- Average corpus score: {summary['average_corpus_score']}",
        f"- Average selected-template target baseline: {summary['average_selected_template_target_score']}",
        f"- Selected target template count: {summary['selected_target_template_count']}",
        "",
        "## Score Bands",
        "",
    ]
    for band in ("90+", "85-90", "82-85", "80-82", "70-80", "60-70", "<60"):
        lines.append(f"- {band}: {score_bands.get(band, 0)}")

    lines.extend(
        [
            "",
            "| Case | Family | Class | Attempts | Pass score | Target score | Corpus score | Template baseline | Candidate |",
            "|---|---|---|---:|---:|---:|---:|---:|---|",
        ]
    )
    for r in results:
        best = best_attempts[r.case.case_id]
        target = best.target_score if best and best.target_score is not None else 0.0
        corpus = best.corpus_score if best and best.corpus_score is not None else 0.0
        candidate = best.candidate if best and best.candidate else ""
        baseline = r.case.selected_template_target_score or 0.0
        lines.append(
            f"| `{r.case.case_id}` | {r.case.family} | {classifications[r.case.case_id]} | "
            f"{len(r.attempts)} | {r.best_score:.1f} | {target:.1f} | {corpus:.1f} | "
            f"{baseline:.1f} | `{candidate}` |"
        )

    lines.extend(
        [
            "",
            "## Retry Stops",
            "",
            "| Case | Reason |",
            "|---|---|",
        ]
    )
    stopped = [r for r in results if r.retry_stopped_early]
    if stopped:
        for r in stopped:
            lines.append(f"| `{r.case.case_id}` | {r.retry_stop_reason or ''} |")
    else:
        lines.append("| None | |")

    lines.extend(
        [
            "",
            "## Legacy Table",
            "",
            "| Case | Family | Passed | Pass score | Target score | Corpus score | Target template | Candidate |",
            "|---|---|---:|---:|---:|---:|---:|---|",
        ]
    )
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
            "| Case | Reference | Selected template | Template baseline | Target template | Validator | Target score | Corpus score | Best corpus reference |",
            "|---|---|---|---:|---:|---:|---:|---:|---|",
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
        baseline = r.case.selected_template_target_score or 0.0
        lines.append(
            f"| `{r.case.case_id}` | `{reference}` | `{selected}` | "
            f"{baseline:.1f} | "
            f"{str(r.case.selected_template_is_target).lower()} | {validator} | "
            f"{target_score:.1f} | {corpus_score:.1f} | `{best_ref}` |"
        )

    lines.extend(
        [
            "",
            "## Selector Candidates",
            "",
            "| Case | Primary visual fallback | Selected score | Top candidates |",
            "|---|---|---:|---|",
        ]
    )
    for r in results:
        compact = []
        for c in r.case.selector_candidates[:5]:
            compact.append(f"{Path(c['path']).name} ({c['score']:.1f})")
        primary = ""
        if r.case.style_neighbor_hints:
            primary = f"{r.case.style_neighbor_hints[0]['name']} ({r.case.style_neighbor_hints[0]['score']:.1f})"
        lines.append(f"| `{r.case.case_id}` | `{primary}` | {r.case.selected_template_score:.1f} | {'; '.join(compact)} |")

    lines.extend(
        [
            "",
            "## Suggested Improvement Review",
            "",
            "- Treat `ceiling-limited` cases as template-coverage gaps. The selected alternate SAP layout is already too far below the target; more Ollama attempts are unlikely to fix geometry, canvas rhythm, icon count, or edge topology.",
            "- Treat `near-miss` cases as useful retry targets. These are close enough that label replacements, small template-selection changes, or one extra sibling template can move them over the threshold.",
            "- Compare low-scoring candidates with `compare.py <reference> <candidate>` and add sibling templates or targeted selector metadata when the baseline score is below the retry floor.",
            "- Convert recurring diffs into `SKILL.md`, selector, validator, autofix, or curated template updates.",
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
            raw_model_output, model_json_text, model_error = call_ollama(
                case,
                args.model,
                args.timeout_seconds,
                args.ollama_endpoint,
                args.temperature,
            )
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
        "ollama_endpoint": args.ollama_endpoint if args.generator == "ollama" else None,
        "temperature": args.temperature if args.generator == "ollama" else None,
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
    try:
        cases = build_generation_cases(args)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    print(f"dry-run cases: {len(cases)}")
    print(f"generator    : {args.generator}")
    print(f"pass mode    : {args.pass_mode}")
    print(f"retry margin : {args.retry_margin}")
    print(f"exclude target template: {str(args.exclude_target_template).lower()}")
    print(f"apply model plan: {str(args.apply_model_plan).lower()}")
    if args.from_run:
        print(f"from run     : {args.from_run}")
    if args.case_class:
        print(f"case classes : {', '.join(args.case_class)}")
    if args.case_id:
        print(f"case filters : {', '.join(args.case_id)}")
    if args.generator == "ollama":
        print(f"model        : {args.model}")
        print(f"endpoint     : {args.ollama_endpoint}")
        print(f"temperature  : {args.temperature}")
    for case in cases:
        print(f"- {case.case_id}: {case.title}")
        print(f"  target  : {case.reference}")
        print(f"  template: {case.selected_template} score={case.selected_template_score:.1f} (target={str(case.selected_template_is_target).lower()})")
        if case.selected_template_target_score is not None:
            print(f"  baseline: target-score={case.selected_template_target_score:.1f}")
        if case.style_neighbor_hints:
            neighbors = ", ".join(f"{item['name']}:{item['score']:.1f}" for item in case.style_neighbor_hints)
            print(f"  visual  : {neighbors}")
        if case.selector_candidates:
            top = ", ".join(f"{Path(c['path']).name}:{c['score']:.1f}" for c in case.selector_candidates[:3])
            print(f"  top     : {top}")
    return 0


def cmd_generate(args: argparse.Namespace) -> int:
    try:
        cases = build_generation_cases(args)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
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
    try:
        cases = build_generation_cases(args)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
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
    parser.add_argument("--ollama-endpoint", default=DEFAULT_OLLAMA_ENDPOINT)
    parser.add_argument(
        "--temperature",
        type=float,
        default=0.0,
        help="Ollama generation temperature. Keep 0 for deterministic structured plans.",
    )
    parser.add_argument("--max-attempts", type=int, default=1)
    parser.add_argument(
        "--retry-margin",
        type=float,
        default=8.0,
        help=(
            "Only retry failed scored cases whose pass score is within this many points "
            "of --min-score. Use a large value such as 100 for exhaustive retries."
        ),
    )
    parser.add_argument("--timeout-seconds", type=int, default=DEFAULT_TIMEOUT_SECONDS)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--min-score", type=float, default=90.0)
    parser.add_argument("--pass-mode", choices=("target", "corpus", "both"), default="target")
    parser.add_argument("--exclude-target-template", action="store_true")
    parser.add_argument(
        "--no-style-neighbor-hints",
        action="store_true",
        help="Disable target-reference visual-neighbor hints in leave-one-out evaluation runs",
    )
    parser.add_argument("--apply-model-plan", action="store_true", help="For Ollama runs, apply conservative label replacements from model JSON")
    parser.add_argument(
        "--from-run",
        type=Path,
        help="Previous eval run directory or summary.json used to select cases for a focused rerun",
    )
    parser.add_argument(
        "--case-class",
        action="append",
        choices=("passed", "failed", "near-miss", "ceiling-limited", "model-failure", "validator-failure", "not-run"),
        help="Rerun only cases with this class in --from-run. Repeat for multiple classes.",
    )
    parser.add_argument(
        "--case-id",
        action="append",
        default=None,
        help="Filter cases by substring across case id, family, title, or reference filename. Repeat to narrow further.",
    )
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
