#!/usr/bin/env python3
"""Rank SAP reference templates for a natural-language diagram request.

This is intentionally simple and dependency-free. The goal is not semantic
search; it is to stop the author from guessing which SAP template to start
from. The script scores filenames plus visible labels in each .drawio file,
adds scenario-family boosts, and prints the best candidates.

Usage:
  select_reference.py "CAP app with XSUAA and HANA Cloud"
  echo "Joule agent calls S/4HANA through MCP" | select_reference.py
  select_reference.py --top 10 --json "Business Data Cloud with Databricks"
"""
from __future__ import annotations

import argparse
import html
import json
import re
import sys
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass, field
from functools import lru_cache
from pathlib import Path

STOPWORDS = {
    "a", "an", "and", "app", "apps", "arch", "architecture", "as", "at", "between",
    "btp", "by", "cloud", "create", "diagram", "draw", "for", "from", "in",
    "into", "is", "l0", "l1", "l2", "landscape", "make", "my", "of", "on", "or",
    "ref", "reference", "sap", "show", "solution", "the", "to", "using",
    "via", "with",
    # Generic prompt framing words. Keeping these out avoids accidental matches
    # such as "Architecture Center" -> Task Center.
    "center", "convention", "conventions", "horizon", "icon", "icons",
    "label", "labels", "palette", "preserve", "readable", "rhythm",
    "semantic", "semantics", "style", "template", "visual", "zone",
    "zones",
}
TOKEN_CANONICAL = {
    "adminstrator": "administrator",
    "admin": "administrator",
    "plaforms": "platforms",
    "provisoning": "provisioning",
    "ressources": "resources",
    "s": "s4hana",
    "4hana": "s4hana",
}

SCENARIOS = [
    {
        "name": "identity-authentication",
        "query": {"ias", "identity", "authentication", "authn", "oauth", "oidc", "saml", "single", "sign", "sso", "xsuaa", "jwt", "trust"},
        "reference": {"identity", "authentication", "authn", "iam", "xsuaa", "ias", "joule_iam"},
        "boost": 18,
    },
    {
        "name": "identity-authorization",
        "query": {"authorization", "authz", "role", "roles", "scope", "scopes", "permission", "permissions", "rbac"},
        "reference": {"authorization", "authz", "iam", "identity"},
        "boost": 18,
    },
    {
        "name": "private-connectivity",
        "query": {"private", "privatelink", "link", "connectivity", "connector", "cloudconnector", "scc", "onprem", "premise", "principal", "principalpropagation", "propagation", "odata"},
        "reference": {"privatelink", "private", "connector", "cloudconnector", "connectivity", "odata", "e2b"},
        "boost": 17,
    },
    {
        "name": "agentic-ai-mcp",
        "query": {"agent", "agents", "agentic", "mcp", "a2a", "tool", "tools", "joule", "copilot", "cline", "llm"},
        "reference": {"agent", "agentic", "mcp", "a2a", "joule", "genai", "generative"},
        "boost": 17,
    },
    {
        "name": "generative-ai-rag",
        "query": {"genai", "generative", "rag", "retrieval", "semantic", "embedding", "embeddings", "vector", "prompt"},
        "reference": {"genai", "generative", "rag", "semantic", "agent2agent"},
        "boost": 16,
    },
    {
        "name": "business-data-cloud",
        "query": {"bdc", "business", "data", "databricks", "snowflake", "hana", "datasphere", "analytics", "bw"},
        "reference": {"bdc", "businessdatacloud", "databricks", "hyperscalerdata", "dataintegration"},
        "boost": 15,
    },
    {
        "name": "event-driven-integration",
        "query": {"event", "events", "eventmesh", "eventing", "eda", "queue", "queues", "kafka", "message", "messages"},
        "reference": {"eventdriven", "eda", "event", "integration", "e2b", "a2aintegration", "b2bintegration"},
        "boost": 15,
    },
    {
        "name": "resiliency",
        "query": {"resiliency", "resilience", "multi", "region", "availability", "az", "failover", "load", "balancer", "disaster"},
        "reference": {"resiliency", "multiregion", "multiaz", "loadbalancer"},
        "boost": 14,
    },
    {
        "name": "multitenant-saas-cap",
        "query": {"cap", "saas", "tenant", "tenants", "multitenant", "multitenancy", "subscription"},
        "reference": {"susaas", "cap", "multitenant"},
        "boost": 14,
    },
    {
        "name": "task-workflow-workzone",
        "query": {"task", "tasks", "inbox", "workflow", "workzone", "work", "zone", "launchpad", "process", "automation", "spa"},
        "reference": {"taskcenter", "buildworkzone", "buildprocessautomation"},
        "boost": 14,
    },
    {
        "name": "devops",
        "query": {"devops", "cicd", "ci", "cd", "pipeline", "pipelines", "transport", "deploy", "deployment"},
        "reference": {"devops"},
        "boost": 20,
    },
    {
        "name": "security-operations",
        "query": {"siem", "soar", "threat", "detection", "audit", "security", "etd"},
        "reference": {"siem", "soar", "etd"},
        "boost": 20,
    },
    {
        "name": "federated-ml",
        "query": {"federated", "ml", "machine", "learning", "training", "model", "models", "aicore", "ai"},
        "reference": {"federated", "ml", "machine", "learning", "aicore", "ai"},
        "boost": 22,
    },
    {
        "name": "edge-integration-cell",
        "query": {"edge", "eic", "cell", "pipo", "pi", "po", "runtime", "migration"},
        "reference": {"edge", "eic", "cell", "pipo", "integration"},
        "boost": 20,
    },
    {
        "name": "successfactors",
        "query": {"successfactors", "hxm", "bizx", "employee", "recruiting", "module", "modules", "talent"},
        "reference": {"successfactors", "hxm", "bizx", "recruiting"},
        "boost": 22,
    },
]


@dataclass
class Candidate:
    path: str
    score: float
    reasons: list[str] = field(default_factory=list)
    token_hits: list[str] = field(default_factory=list)
    metadata_title: str | None = None
    metadata_tags: list[str] = field(default_factory=list)


def default_reference_dir() -> Path:
    return Path(__file__).resolve().parents[1] / "assets" / "reference-examples"


def metadata_path_for(reference_dir: Path) -> Path:
    return reference_dir / "template-metadata.json"


@lru_cache(maxsize=8)
def load_metadata(reference_dir_text: str) -> dict:
    path = metadata_path_for(Path(reference_dir_text))
    if not path.exists():
        return {"templates": {}}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"templates": {}}


def template_metadata(path: Path) -> dict:
    metadata = load_metadata(str(path.parent.resolve()))
    return metadata.get("templates", {}).get(path.name, {})


def metadata_search_text(path: Path, metadata: dict | None = None) -> str:
    metadata = metadata if metadata is not None else template_metadata(path)
    if not metadata:
        return ""
    parts: list[str] = []
    for key in ("title", "summary", "family", "level", "domain"):
        val = metadata.get(key)
        if isinstance(val, str):
            parts.append(val)
    for key in ("aliases", "tags", "products", "fallback_templates"):
        vals = metadata.get(key)
        if isinstance(vals, list):
            parts.extend(str(v) for v in vals)
    return " ".join(parts)


def explicit_metadata_title(path: Path) -> str | None:
    val = template_metadata(path).get("title")
    return str(val) if val else None


def split_words(text: str) -> list[str]:
    text = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1 \2", text)
    text = re.sub(r"([a-z])([A-Z])", r"\1 \2", text)
    text = text.replace("_", " ").replace("-", " ").replace("/", " ")
    return [t.lower() for t in re.findall(r"[A-Za-z0-9]+", text)]


def tokens(text: str) -> set[str]:
    out: set[str] = set()
    for t in split_words(text):
        t = TOKEN_CANONICAL.get(t, t)
        if len(t) >= 2 and t not in STOPWORDS:
            out.add(t)
    joined = "".join(split_words(text))
    for compact in (
        "xsuaa",
        "privatelink",
        "workzone",
        "taskcenter",
        "eventmesh",
        "multiaz",
        "multiregion",
        "businessdatacloud",
        "successfactors",
        "cloudconnector",
        "principalpropagation",
    ):
        if compact in joined:
            out.add(compact)
    if "businessdatacloud" in out:
        out.add("bdc")
    if "aicore" in joined or {"ai", "core"} <= out:
        out.add("aicore")
    if "cloudconnector" in joined:
        out.add("cloudconnector")
    if "principalpropagation" in joined:
        out.add("principalpropagation")
    if "s4hana" in joined or "4hana" in out or {"s4", "hana"} <= out:
        out.add("s4hana")
    if {"ci", "cd"} <= out:
        out.add("cicd")
    if {"pi", "po"} <= out:
        out.add("pipo")
    if {"edge", "integration", "cell"} <= out:
        out.add("eic")
    return out


def drawio_text(path: Path) -> str:
    raw = path.read_text(encoding="utf-8", errors="ignore")
    parts = [path.stem]
    try:
        root = ET.fromstring(raw)
        for elem in root.iter():
            for attr in ("name", "label", "value"):
                val = elem.get(attr)
                if val:
                    parts.append(val)
    except ET.ParseError:
        parts.append(raw[:10000])
    visible = html.unescape(" ".join(parts))
    visible = re.sub(r"<br\s*/?>", " ", visible, flags=re.I)
    visible = re.sub(r"<[^>]+>", " ", visible)
    return visible


def phrase_hits(query: str, phrases: list[str]) -> list[str]:
    query_clean = " ".join(split_words(query))
    hits: list[str] = []
    for phrase in phrases:
        phrase_clean = " ".join(split_words(str(phrase)))
        if len(phrase_clean) >= 4 and phrase_clean in query_clean:
            hits.append(str(phrase))
    return hits


def exact_stem_mentioned(path: Path, query: str) -> bool:
    query_lower = query.lower()
    if path.name.lower() in query_lower:
        return True
    stem_words = " ".join(split_words(path.stem))
    query_words = " ".join(split_words(query))
    return len(stem_words) >= 8 and stem_words in query_words


def primary_visual_fallback_mentioned(path: Path, query: str) -> bool:
    match = re.search(r"Primary SAP visual fallback template:\s*([A-Za-z0-9_.-]+)", query, flags=re.I)
    if not match:
        return False
    return match.group(1).strip().rstrip(".").lower() == path.name.lower()


def explicit_level(query: str) -> str | None:
    m = re.search(r"\bL([012])\b", query, flags=re.I)
    return f"l{m.group(1)}" if m else None


def explicit_family(query: str) -> str | None:
    m = re.search(r"\bRA(\d{4})\b", query, flags=re.I)
    return f"ra{m.group(1)}" if m else None


def score(path: Path, query: str) -> Candidate:
    q_tokens = tokens(query)
    metadata = template_metadata(path)
    doc_text = drawio_text(path)
    meta_text = metadata_search_text(path, metadata)
    d_tokens = tokens(doc_text)
    m_tokens = tokens(meta_text)
    filename_tokens = tokens(path.stem)
    combined_tokens = d_tokens | m_tokens

    token_hits = sorted(q_tokens & combined_tokens)
    value = len(token_hits) * 2.0
    reasons: list[str] = []
    if token_hits:
        reasons.append("token overlap: " + ", ".join(token_hits[:8]))

    filename_hits = sorted(q_tokens & filename_tokens)
    if filename_hits:
        value += len(filename_hits) * 4.0
        reasons.append("filename match: " + ", ".join(filename_hits[:8]))

    if exact_stem_mentioned(path, query):
        value += 70
        reasons.append("exact template filename mentioned (+70)")

    if primary_visual_fallback_mentioned(path, query):
        value += 90
        reasons.append("primary visual fallback match (+90)")

    meta_hits = sorted(q_tokens & m_tokens)
    if meta_hits:
        boost = min(36.0, len(meta_hits) * 4.0)
        value += boost
        reasons.append("metadata match: " + ", ".join(meta_hits[:8]) + f" (+{int(boost)})")

    alias_hits = phrase_hits(query, metadata.get("aliases", []) if isinstance(metadata.get("aliases"), list) else [])
    if alias_hits:
        boost = min(30.0, 12.0 + (len(alias_hits) - 1) * 6.0)
        value += boost
        reasons.append("alias phrase match: " + ", ".join(alias_hits[:3]) + f" (+{int(boost)})")

    title = metadata.get("title")
    if isinstance(title, str) and phrase_hits(query, [title]):
        value += 22
        reasons.append("metadata title phrase match (+22)")

    level = explicit_level(query)
    family = explicit_family(query)
    filename_lower = path.name.lower()
    path_lower = str(path).lower()
    metadata_family = str(metadata.get("family", "")).lower()
    metadata_level = str(metadata.get("level", "")).lower()
    if family:
        if family in path_lower or family == metadata_family:
            value += 24
            reasons.append(f"explicit {family.upper()} family match (+24)")
        elif re.search(r"\bra\d{4}\b", path_lower):
            value -= 8
            reasons.append("different reference family penalty (-8)")
        else:
            value -= 5
            reasons.append("different reference source penalty (-5)")
    if level:
        if level in filename_lower or level == metadata_level:
            value += 10
            reasons.append(f"explicit {level.upper()} match")
        elif re.search(r"_l[012]\b", filename_lower):
            value -= 3
    elif "_l2" in filename_lower:
        value += 3
        reasons.append("default L2 preference")

    for scenario in SCENARIOS:
        q_hit = q_tokens & scenario["query"]
        r_hit = filename_tokens & scenario["reference"]
        if not r_hit:
            r_hit = m_tokens & scenario["reference"]
        if q_hit and r_hit:
            boost = float(scenario["boost"])
            value += boost
            reasons.append(f"{scenario['name']} boost (+{int(boost)})")

    strong_query_tags = {
        "devops",
        "federated",
        "ml",
        "eic",
        "pipo",
        "siem",
        "soar",
        "successfactors",
        "embodied",
        "agentic",
    } & q_tokens
    if strong_query_tags and not (strong_query_tags & (filename_tokens | m_tokens)):
        value -= 10
        reasons.append("strong scenario mismatch penalty (-10)")

    if q_tokens & {"mcp", "a2a"} and filename_tokens & {"mcp", "a2a"}:
        value += 20
        reasons.append("exact MCP/A2A filename match (+20)")
    if q_tokens & {"xsuaa", "oauth", "oidc", "saml"} and (
        {"authentication", "authn"} & filename_tokens or "cloud" in filename_lower and "identity" in filename_lower
    ):
        value += 8
        reasons.append("exact authentication filename match (+8)")
    if q_tokens & {"bdc", "businessdatacloud", "aicore"} and filename_tokens & {"bdc", "businessdatacloud", "aicore"}:
        value += 12
        reasons.append("exact BDC / AI Core filename match (+12)")
    if "aicore" in q_tokens and "aicore" in filename_tokens:
        value += 10
        reasons.append("exact AI Core filename match (+10)")
    if "joule" in filename_tokens and "joule" not in q_tokens:
        value -= 12
        reasons.append("Joule-specific template penalty (-12)")
    if metadata.get("generic") and strong_query_tags:
        value -= 12
        reasons.append("generic template penalty for specific scenario (-12)")

    # Prefer canonical btp_ examples when equally relevant; otherwise prefer
    # Architecture Center diagrams with richer scenario labels.
    if path.name.startswith("btp_"):
        value += 1.0
    if not reasons:
        reasons.append("weak lexical match; review manually")

    return Candidate(
        str(path),
        round(value, 1),
        reasons,
        token_hits[:12],
        metadata_title=str(title) if title else None,
        metadata_tags=list(metadata.get("tags", []))[:12] if isinstance(metadata.get("tags"), list) else [],
    )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("description", nargs="*", help="diagram request; stdin is used if omitted")
    ap.add_argument("--reference-dir", type=Path, default=default_reference_dir())
    ap.add_argument("--top", type=int, default=5)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    query = " ".join(args.description).strip() or sys.stdin.read().strip()
    if not query:
        print("description required", file=sys.stderr)
        return 2
    if not args.reference_dir.exists():
        print(f"{args.reference_dir}: reference directory not found", file=sys.stderr)
        return 2

    refs = sorted(args.reference_dir.rglob("*.drawio"))
    ranked = sorted((score(p, query) for p in refs), key=lambda c: (-c.score, c.path))[: args.top]

    if args.json:
        print(json.dumps([asdict(c) for c in ranked], indent=2))
        return 0

    print(f"query: {query}")
    for i, cand in enumerate(ranked, 1):
        print(f"{i}. {cand.score:5.1f}  {cand.path}")
        for reason in cand.reasons[:3]:
            print(f"   - {reason}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
