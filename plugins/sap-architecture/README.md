# sap-architecture plugin

Claude Code plugin that generates, validates, and autofixes SAP / BTP / on-prem architecture diagrams as `.drawio` files following the official [SAP BTP Solution Diagram Guidelines](https://sap.github.io/btp-solution-diagrams/).

> See the [root README](../../README.md) for install instructions across Claude Code, Claude Desktop, and other Agent-Skills runtimes. This file covers the plugin internals.

## Install (Claude Code)

```
/plugin marketplace add marianfoo/btp-drawio-skill
/plugin install sap-architecture
```

## What it ships

```
sap-architecture/
├── .claude-plugin/plugin.json             — plugin manifest
└── skills/
    └── sap-architecture/
        ├── SKILL.md                       — main workflow (6 steps, <500 lines)
        ├── references/                    — loaded on demand by SKILL.md
        │   ├── levels.md                  — L0/L1/L2 decision guide
        │   ├── palette-and-typography.md  — Horizon hex + Helvetica + SAP rules
        │   ├── shapes-and-edges.md        — style strings + line / connector semantics
        │   ├── layout.md                  — canvas skeleton + zone-by-zone placement
        │   ├── do-and-dont.md             — consolidated SAP rules with verbatim quotes
        │   ├── corpus-findings.md         — 2026 SAP corpus profile
        │   ├── generation-quality.md      — research-backed output checklist
        │   ├── external-test-corpus.md    — optional external SAP corpus for longer runs
        │   ├── improvement-options.md     — researched ranking of quality-improvement options
        │   └── methodology.md             — comparison harness, fidelity claim
        ├── assets/
        │   ├── libraries/                 — 10 SAP draw.io starter-kit libraries
        │   ├── reference-examples/        — 71 pristine SAP templates
        │   │                                  11 from SAP/btp-solution-diagrams (btp_)
        │   │                                  52 from SAP/architecture-center (ac_)
        │   │   └── template-metadata.json — curated scenario titles, aliases, tags, levels
        │   ├── icon-index.json            — pre-computed slug → mxCell style lookup
        │   ├── asset-index.json           — 448 searchable SAP draw.io assets
        │   └── NOTICE.md                  — per-file SAP attribution (Apache-2.0)
        ├── examples/
        │   └── iam-arc1-mcp-l2.drawio     — worked example (96.6 vs source template; 100 self-check)
        └── scripts/
            ├── build_icon_index.py        — regenerate icon-index.json
            ├── build_asset_index.py       — regenerate asset-index.json
            ├── extract_icon.py            — fuzzy icon name → mxCell
            ├── extract_asset.py           — fuzzy starter-kit asset → mxCell snippet
            ├── check_asset_coverage.py    — library/index/palette smoke check
            ├── validate.py                — structural + style validator (catches dark bg, novelty pills)
            ├── autofix.py                 — mechanical fixes
            ├── scaffold_diagram.py        — copy the closest SAP template (mandatory first step)
            ├── select_reference.py        — prompt → ranked SAP templates
            ├── template_browser.py        — pre-render all 71 templates into a thumbnail gallery
            ├── render.py                  — drawio CLI wrapper (export to PNG/SVG/PDF)
            ├── render_compare.py          — render candidate + reference + side-by-side HTML review
            ├── compare.py                 — pairwise fingerprint score vs SAP refs
            ├── score_corpus.py            — best score across the reference corpus
            └── eval_corpus.py             — smoke-first Ollama corpus evaluation loop
```

## How it triggers

The `description` field in `SKILL.md` is front-loaded with SAP-diagram trigger keywords. Claude auto-invokes on natural-language prompts like:

- "Create an SAP architecture diagram for …"
- "Draw my BTP deployment"
- "Diagram the XSUAA OAuth flow"
- "Show how MCP client connects on-prem SAP via Cloud Connector"
- "Make an L0/L1/L2 SAP ref-arch for …"
- "Like the SAP Architecture Center style"

For generic diagrams (flowcharts, ER, class) **without** an SAP angle, Claude falls through to whatever general drawio skill you have installed. No conflict.

## What to include in a good prompt

Give the skill enough architectural context to choose a SAP reference template:

- diagram level and audience: `L0`, `L1`, or `L2` (default)
- main zones: user/client, SAP BTP, SAP cloud applications, on-premise, third-party/hyperscaler, network divider
- exact SAP BTP services and runtime: Cloud Foundry, Kyma, CAP, XSUAA, Destination, Connectivity, Event Mesh, Integration Suite, HANA Cloud, etc.
- backend systems: SAP S/4HANA, ECC, BW/4HANA, SuccessFactors, Datasphere, Databricks, and whether they are cloud or on-premise
- identity/trust: IAS, XSUAA, OAuth, SAML, Principal Propagation, trust, authorization
- numbered flow steps with protocols or intents: `HTTPS`, `OData/REST`, `A2A`, `MCP`, `ORD`, `SQL`, `Data Federation`
- constraints: template to prefer, zones that must be separate, what not to include

If you paste a long design document, add a short scope sentence that says which one flow should become the diagram. Otherwise the agent may mix levels or include unrelated components.

## Workflow (what happens when triggered)

1. **Lock semantics** — create a JSON contract for required zones, nodes, directed flows, terms, and exclusions before template selection.
2. **Scaffold and pin** — run `scaffold_diagram.py`, copy the closest SAP template, and retain that exact file as the target. Never write XML from scratch.
3. **Sanitize provenance** — run `provenance.py` before editing to mark the derivative, remove detectable official identifiers/links, add visible attribution, and surface ambiguous QR-like raster images for review.
4. **Edit surgically** — relabel and use official library assets; remove complete irrelevant branches and keep the semantic contract synchronized.
5. **Run guarded gates** — autofix, semantic validation, strict provenance audit, and either zero new warnings plus pinned-template score at least 90 (template mode), or zero warnings plus SAP-likeness at least 90 (justified semantic fallback).
6. **Render and inspect** — `verify_delivery.py` creates candidate/reference PNGs and stops at `awaiting-visual-review`; inspect both and record a hash-bound review with `record_visual_review.py`.
7. **Complete and narrate** — rerun `verify_delivery.py` to `pass`, then print the numbered flow narration below the diagram.

Full details in [`skills/sap-architecture/SKILL.md`](skills/sap-architecture/SKILL.md).

## Scripts

All scripts use only the Python standard library — zero pip install required.

| Script | Purpose |
|---|---|
| `extract_icon.py "<name>"` | Fuzzy-lookup a BTP service icon; emit ready-to-paste `<mxCell>` with grid-snapped geometry. Supports abbreviations (XSUAA, CPI, HANA, CC, IAS, IPS, CAP, CF). `--list` shows all 100. |
| `extract_asset.py "<name>" --kind <kind>` | Fuzzy-lookup any indexed SAP starter-kit asset: generic icons, connectors, area/default shapes, essentials, number markers, brand names, text elements, annotations/interfaces, and BTP service icons. |
| `relabel.py <file> <labels.json> --out <file>` | Deterministically replace labels by cell id or visible label while preserving simple rich-text wrappers. Use before hand-editing XML. |
| `scaffold_diagram.py "<request>" --out <file>` | Copy the closest SAP reference template to a destination so editing starts from a pristine SAP-style file. Supports `--template` for an explicit pick, `--dry-run` to inspect candidates, and `--diagram-name` to rename the page. **The mandatory first step of the skill.** |
| `render_semantic.py "<request>" --out <file>` | Deterministic SAP-style fallback renderer for ceiling-limited prompts. Supports `security-operations`, `devops`, `on-prem-connectivity`, `private-connectivity`, `btp-application`, `data-integration`, `integration-flow`, and `ai-agent`. |
| `render.py <file>.drawio` | Render a `.drawio` file to PNG/SVG/PDF via the draw.io desktop CLI. Auto-discovers the binary on macOS, Linux, WSL2; honor `$DRAWIO_CLI` to override. `--batch <dir>` renders every diagram in a folder. |
| `render_compare.py <ref>.drawio <cand>.drawio --open` | Render both files to PNG and emit `review.html` with side-by-side images, structural score breakdown, and **actionable suggestions mapped to the lowest-scoring fingerprint dimensions**. The fastest visual review for the manual-iteration loop. |
| `template_browser.py` | Pre-render all 71 bundled SAP templates into a thumbnail gallery with filter, domain badges, and the exact `scaffold_diagram.py --template …` command for each. Useful when you need to pick the right starting template visually. |
| `select_reference.py "<request>"` | Rank bundled SAP templates for a natural-language request using curated metadata, filenames, aliases, levels, and visible labels. Use before editing XML. |
| `validate.py <file>` | Structural + style validator. Catches bent arrows, text overflow, off-palette, off-grid, duplicate ids, sibling overlap, missing `labelBackgroundColor`. `--strict` turns warnings into errors. `--json` for machine-readable output. |
| `validate_semantics.py <file> <spec.json>` | Enforce the pre-authored request contract: required zones/nodes/terms, forbidden terms, and directed flows. |
| `provenance.py <file> ...` | Mark a derivative, strip detectable source identifiers/links, add visible attribution, and block unresolved QR-like raster images. |
| `verify_delivery.py <file> <spec.json> --target <template>` | Run semantic, provenance, strict structural-delta, pinned-template, rendering, and hash-bound visual-review gates. |
| `record_visual_review.py <candidate.png> <reference.png> ...` | Create the machine-readable visual-review record only after all required pixel checks were performed. |
| `autofix.py --write <file>` | Mechanical fixer: grid snap, hex case, `absoluteArcSize=1`, `strokeWidth` rounding, `fontFamily`→Helvetica. Writes a `.bak` backup. |
| `compare.py <reference> <candidate>` | Pairwise structural/style/content fingerprint score. |
| `score_corpus.py <candidate>` | Report corpus similarity plus reference-free SAP-likeness; use `--min-score 90` for template-derived diagrams and `--min-sap-like 90` for semantic fallback diagrams. |
| `eval_corpus.py create "..."` | Create one diagram from a natural-language description, optionally with Ollama planning and model-plan label application. |
| `eval_corpus.py run --generator ollama` | Opt-in target-aware corpus loop for local Ollama experiments. Use `--exclude-target-template` to prevent copying the target; the harness then uses closest visual-neighbor hints unless `--no-style-neighbor-hints` is set. Reports selected-template baseline score, near-miss vs ceiling-limited failures, and uses `--retry-margin` to avoid repeated attempts when the alternate SAP layout is already too far from the target. Use `--from-run <run-dir> --case-class near-miss` for focused reruns and `--case-id <substring>` for manual family tests. Writes candidates and reports under `.cache/sap-architecture-eval/`. |
| `build_icon_index.py` | Re-parse the BTP service icon library into `assets/icon-index.json`. Run after refreshing the library from SAP upstream. |
| `build_asset_index.py` | Re-parse all bundled SAP draw.io libraries into `assets/asset-index.json`. |
| `check_asset_coverage.py` | Smoke-check library presence, index counts, SAP Build coverage, and official SAP preset colors. |

See [root README › Use the scripts directly](../../README.md#use-the-scripts-directly-no-llm) for full examples.

## Customization

The plugin respects your existing `.drawio` conventions via two lightweight extension points:

1. **Custom style overrides** — add a `references/custom-overrides.md` to your checkout; SKILL.md will read it if present and let those rules take precedence over the defaults.
2. **Custom icon set** — drop extra XML libraries into `assets/libraries/` and run `scripts/build_icon_index.py` plus `scripts/build_asset_index.py` to re-index.

## License

- Plugin code: MIT (see [root LICENSE](../../LICENSE))
- Bundled SAP assets under `skills/sap-architecture/assets/`: Apache-2.0, © SAP SE — see [`skills/sap-architecture/assets/NOTICE.md`](skills/sap-architecture/skills/sap-architecture/assets/NOTICE.md)
