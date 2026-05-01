# Improvement options for higher SAP diagram fidelity

Research snapshot: 2026-05-01.

The goal is not generic diagram generation. The goal is editable `.drawio` output that looks close to SAP Architecture Center and SAP BTP Solution Diagram examples. That changes the ranking: preserving SAP-authored geometry, icons, colors, and notation is more important than asking a model to invent a new layout.

## High-value options implemented

### 1. Template-first generation

Status: implemented earlier and kept as the primary workflow.

Why it fits: SAP explicitly provides reusable examples/templates and starter-kit libraries so authors do not start from scratch. The local corpus results show the same thing empirically: a template-derived candidate can score near the source template, while from-scratch candidates lose canvas rhythm, icon counts, line topology, and typography.

Implementation consequence: `select_reference.py` picks a SAP-authored template, `eval_corpus.py` copies that template, and model output is allowed to make conservative label edits only. This keeps geometry, colors, icon data URIs, edge styles, and area shapes intact.

Sources:
- https://sap.github.io/btp-solution-diagrams/docs/solution_diagr_intro/intro/
- https://architecture.learning.sap.com/news/2026/04/22/introducing-the-refreshed-sap-architecture-center

### 2. Structured generation plan instead of free-form model text

Status: implemented in `eval_corpus.py`.

Why it fits: Ollama supports a JSON schema in the `format` field for `/api/generate`, and its docs recommend low temperature for deterministic structured output. The harness now uses the HTTP API with a schema for `title`, `subtitle`, `services`, `flow_steps`, `style_risks`, and `template_replacements`, falling back to the CLI only if the API is unavailable.

Expected impact: fewer parse failures, less markdown/control-token cleanup, and more consistent plan fields across long overnight runs. It does not solve geometry by itself, but it makes model output reliable enough for the deterministic template adapter.

Sources:
- https://docs.ollama.com/capabilities/structured-outputs
- https://docs.ollama.com/api/generate

### 3. Score-feedback retries

Status: implemented in `eval_corpus.py`.

Why it fits: DiagrammerGPT-style systems separate diagram planning from rendering and use iterative feedback to refine the plan. For this plugin, the renderer is deterministic template copying plus guarded label edits, so the useful feedback is the validator result, target score, weak fingerprint dimensions, target diffs, and rejected label replacements.

Expected impact: near-miss cases get a real second/third attempt instead of another independent generation. Ceiling-limited cases still stop early when the selected alternate template is too far from the target, because label feedback cannot fix a missing layout family.

Sources:
- https://diagrammergpt.github.io/
- https://arxiv.org/abs/2510.25761

## High-value options already available but opt-in

### 4. Larger SAP reference corpus

Status: documented in `external-test-corpus.md`.

Why it fits: SAP Architecture Center is a living platform and now includes current Agentic AI/Joule content. The optional `SAP/sap-btp-reference-architectures` corpus adds older BTP reference patterns that are useful stress cases. External corpora should stay under `.cache/` unless a license-compatible fixture is intentionally promoted.

Expected impact: better selector coverage and clearer evidence about which families need curated templates. It is especially useful for finding ceiling-limited cases where a new SAP-authored template is worth bundling.

Sources:
- https://architecture.learning.sap.com/news/2026/04/22/introducing-the-refreshed-sap-architecture-center
- https://github.com/SAP/sap-btp-reference-architectures

### 5. SAP Architecture Center validation rules

Status: use as semantic review input, not yet an automatic validator.

Why it fits: SAP publishes architecture validation rules, including AI/Joule/MCP-specific constraints. These rules evaluate semantic correctness, while the current local score evaluates visual/style fidelity. They should be added as a second pass after visual fidelity stabilizes.

Expected impact: catches diagrams that look SAP-like but violate SAP architectural guidance, for example MCP paths that bypass Joule or identity-provider flows that bypass SAP Cloud Identity Services.

Source:
- https://architecture.learning.sap.com/docs/validation-rules

## Medium-value options for later

### 6. Screenshot or pixel-level similarity

Status: not implemented.

Why it helps: the current fingerprint score catches structural/style differences in XML, but a rendered screenshot would catch overlaps, visual density, footer/QR placement, and label clipping that XML heuristics can miss.

Why not now: reliable rendering needs draw.io desktop, a containerized diagrams.net export path, or browser automation. It is valuable as a second-stage QA gate, but it adds machine dependencies and runtime cost. Keep this for curated examples and release checks, not every overnight run.

### 7. Graph/node/path alignment metrics

Status: partially approximated by `compare.py`.

Why it helps: research on diagram evaluation models diagrams as graphs and scores node/path alignment. This maps well to architecture diagrams where services are nodes and labeled flows are edges.

Why not now: the `.drawio` corpus does not yet expose a normalized semantic graph for every template. Implementing this properly needs extraction of zones, service cards, icons, and edge endpoints into a canonical graph before scoring.

Source:
- https://arxiv.org/abs/2510.25761

### 8. Embedding-based template retrieval

Status: not implemented.

Why it helps: semantic embeddings could improve template selection when the prompt and SAP reference use different wording.

Why not now: the current failures are mostly visual ceiling/coverage failures rather than pure retrieval failures. BM25-style tags plus visual-neighbor fallback are simpler and explainable. Revisit embeddings when selector candidates are semantically wrong but a good template exists in the corpus.

### 9. Curated domain scenarios from SAP web pages

Status: manual research only.

Why it helps: pages such as SAP AI Golden Path and Agentic AI/Joule reference pages provide current terminology and canonical component grouping.

Why not now: page text should improve descriptions and semantic correctness, but it does not automatically improve visual style unless paired with an existing `.drawio` reference or a new curated template.

Sources:
- https://architecture.learning.sap.com/docs/aigp
- https://architecture.learning.sap.com/docs/golden-path/ai-golden-path/build-and-deliver/build-ai-agents

## Low-value options for this use case

### 10. Direct LLM-generated draw.io XML

Status: avoid.

Why it is low value: draw.io XML contains shape styles, edge metadata, geometry, ids, nested cells, and embedded image data. Direct XML generation tends to produce syntactically fragile or visually off-style diagrams. diagrams.net documents that shapes, connectors, styles, and metadata live in XML, which makes this feasible for deterministic tools but brittle for long free-form model output.

Better alternative: keep XML deterministic. Let the model produce a short structured plan, then apply guarded transformations to a SAP-authored template.

Source:
- https://www.drawio.com/doc/faq/diagram-source-edit

### 11. Generic graph autolayout

Status: avoid for SAP-fidelity generation.

Why it is low value: graph layout engines can make readable diagrams, but they do not know SAP Architecture Center composition, footer rhythm, area nesting, connector semantics, service-card proportions, or grey-circle icon conventions. They are useful only after a semantic graph extractor exists and when no close SAP template exists.

### 12. Fine-tuning or LoRA on SAP diagrams

Status: avoid for now.

Why it is low value: the Apache-2.0 diagram corpus is useful but small, and the target output is editable XML with strict assets. Fine-tuning would be expensive to evaluate and could still invent invalid XML or unusable geometry. Retrieval plus templates plus validation gives better control and is easier to inspect.

## Recommended improvement order

1. Run the bundled leave-one-out suite with structured Ollama output and feedback retries.
2. Rerun only near-misses with `--from-run <run-dir> --case-class near-miss`; this is the only group where extra model attempts are currently likely to help.
3. Review ceiling-limited cases second; add legally compatible SAP templates or improve visual-neighbor selection instead of spending more Ollama attempts.
4. Convert recurring label/selector failures into metadata, prompt rules, or curated template aliases.
5. Run the external SAP corpus only after bundled results stabilize.
6. Add semantic validation rules for SAP AI/Joule/MCP once visual fidelity is consistently high.
7. Add screenshot QA for curated examples and release checks.
