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
        │   └── methodology.md             — comparison harness, fidelity claim
        ├── assets/
        │   ├── libraries/                 — 10 SAP draw.io starter-kit libraries
        │   ├── reference-examples/        — 63 pristine SAP templates
        │   │                                  11 from SAP/btp-solution-diagrams (btp_)
        │   │                                  52 from SAP/architecture-center (ac_)
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
            ├── validate.py                — structural + style validator
            ├── autofix.py                 — mechanical fixes
            ├── select_reference.py        — prompt → ranked SAP templates
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

## Workflow (what happens when triggered)

1. **Parse → plan** — infer level / zones / services / numbered flow / accent app from the description.
2. **Pick reference template** — run `scripts/select_reference.py`, then copy the closest pristine `.drawio` from `assets/reference-examples/`. *Never draw from scratch.*
3. **Place library assets** — call `scripts/extract_icon.py` for each BTP service and `scripts/extract_asset.py` for generic icons, connector presets, number bubbles, interface pills, and other SAP starter-kit assets.
4. **Compose XML** — fill in zones, cards, edges, pills per the four `references/*.md` sheets.
5. **Validate + autofix + score — mandatory** — `autofix.py --write`, `validate.py`, then `score_corpus.py --min-score 90`. Evaluation runs also score against the specific target reference; the skill will not hand back a diagram until the validator exits clean and the fidelity score is high.
6. **Narrate** — print a numbered markdown list explaining each pill / flow step, for pasting below the embedded image in Confluence / Markdown.

Full details in [`skills/sap-architecture/SKILL.md`](skills/sap-architecture/SKILL.md).

## Scripts

All scripts use only the Python standard library — zero pip install required.

| Script | Purpose |
|---|---|
| `extract_icon.py "<name>"` | Fuzzy-lookup a BTP service icon; emit ready-to-paste `<mxCell>` with grid-snapped geometry. Supports abbreviations (XSUAA, CPI, HANA, CC, IAS, IPS, CAP, CF). `--list` shows all 100. |
| `extract_asset.py "<name>" --kind <kind>` | Fuzzy-lookup any indexed SAP starter-kit asset: generic icons, connectors, area/default shapes, essentials, number markers, brand names, text elements, annotations/interfaces, and BTP service icons. |
| `select_reference.py "<request>"` | Rank bundled SAP templates for a natural-language request. Use before editing XML. |
| `validate.py <file>` | Structural + style validator. Catches bent arrows, text overflow, off-palette, off-grid, duplicate ids, sibling overlap, missing `labelBackgroundColor`. `--strict` turns warnings into errors. `--json` for machine-readable output. |
| `autofix.py --write <file>` | Mechanical fixer: grid snap, hex case, `absoluteArcSize=1`, `strokeWidth` rounding, `fontFamily`→Helvetica. Writes a `.bak` backup. |
| `compare.py <reference> <candidate>` | Pairwise structural/style/content fingerprint score. |
| `score_corpus.py <candidate>` | Score a candidate against all bundled references; `--min-score 90` makes it a gate. |
| `eval_corpus.py run --generator ollama` | Opt-in target-aware corpus loop for local Ollama experiments. Use `--exclude-target-template` for honest leave-one-out tests. Writes candidates and reports under `.cache/sap-architecture-eval/`. |
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
