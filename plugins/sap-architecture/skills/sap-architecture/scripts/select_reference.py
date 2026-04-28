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
from pathlib import Path

STOPWORDS = {
    "a", "an", "and", "app", "apps", "architecture", "as", "at", "between",
    "btp", "by", "cloud", "create", "diagram", "draw", "for", "from", "in",
    "into", "l0", "l1", "l2", "landscape", "make", "my", "of", "on", "or",
    "ref", "reference", "sap", "show", "solution", "the", "to", "using",
    "via", "with",
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
        "query": {"private", "privatelink", "link", "connectivity", "connector", "scc", "onprem", "premise", "principal", "propagation", "odata"},
        "reference": {"privatelink", "private", "connector", "connectivity", "odata", "e2b"},
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
        "boost": 13,
    },
    {
        "name": "security-operations",
        "query": {"siem", "soar", "threat", "detection", "audit", "security", "etd"},
        "reference": {"siem", "soar", "etd"},
        "boost": 13,
    },
]


@dataclass
class Candidate:
    path: str
    score: float
    reasons: list[str] = field(default_factory=list)
    token_hits: list[str] = field(default_factory=list)


def default_reference_dir() -> Path:
    return Path(__file__).resolve().parents[1] / "assets" / "reference-examples"


def split_words(text: str) -> list[str]:
    text = re.sub(r"([a-z])([A-Z])", r"\1 \2", text)
    text = text.replace("_", " ").replace("-", " ").replace("/", " ")
    return [t.lower() for t in re.findall(r"[A-Za-z0-9]+", text)]


def tokens(text: str) -> set[str]:
    out: set[str] = set()
    for t in split_words(text):
        if len(t) >= 2 and t not in STOPWORDS:
            out.add(t)
    joined = "".join(split_words(text))
    for compact in ("xsuaa", "privatelink", "workzone", "eventmesh", "multiaz", "multiregion", "businessdatacloud"):
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
    if "s4hana" in joined or "4hana" in out:
        out.add("s4hana")
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


def explicit_level(query: str) -> str | None:
    m = re.search(r"\bL([012])\b", query, flags=re.I)
    return f"l{m.group(1)}" if m else None


def score(path: Path, query: str) -> Candidate:
    q_tokens = tokens(query)
    doc_text = drawio_text(path)
    d_tokens = tokens(doc_text)
    filename_tokens = tokens(path.stem)

    token_hits = sorted(q_tokens & d_tokens)
    value = len(token_hits) * 2.0
    reasons: list[str] = []
    if token_hits:
        reasons.append("token overlap: " + ", ".join(token_hits[:8]))

    filename_hits = sorted(q_tokens & filename_tokens)
    if filename_hits:
        value += len(filename_hits) * 4.0
        reasons.append("filename match: " + ", ".join(filename_hits[:8]))

    level = explicit_level(query)
    filename_lower = path.name.lower()
    if level:
        if level in filename_lower:
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
        if q_hit and r_hit:
            boost = float(scenario["boost"])
            value += boost
            reasons.append(f"{scenario['name']} boost (+{int(boost)})")

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

    # Prefer canonical btp_ examples when equally relevant; otherwise prefer
    # Architecture Center diagrams with richer scenario labels.
    if path.name.startswith("btp_"):
        value += 1.0
    if not reasons:
        reasons.append("weak lexical match; review manually")

    return Candidate(str(path), round(value, 1), reasons, token_hits[:12])


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
