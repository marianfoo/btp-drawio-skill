# btp-drawio-skill

A Claude Code plugin (and Agent-Skill-compatible standalone skill) that authors **SAP Architecture Center / BTP solution diagrams** as draw.io files from a natural-language description — following the **official SAP BTP Solution Diagram Guidelines**.

Bundles:
- **100 SAP BTP service icons** (inline SVG data URIs, grey-background-circle variant — the one [SAP mandates](https://github.com/SAP/btp-solution-diagrams/blob/main/guideline/docs/btp_guideline/diagr_comp/icons.md) for diagrams)
- **448 indexed SAP draw.io starter-kit assets** across 10 bundled libraries: BTP service icons, generic icons, connector presets, area/default shapes, essential shapes, number markers, SAP brand-name text, text elements, and annotation/interface pills
- **63 pristine reference templates** (Apache-2.0): all 11 canonical examples from [`SAP/btp-solution-diagrams`](https://github.com/SAP/btp-solution-diagrams) plus 52 curated reference architectures from [`SAP/architecture-center`](https://github.com/SAP/architecture-center), covering IAM, Joule, MCP / Agentic AI, multitenant SaaS, DevOps, Private Link, Event-Driven Architecture, resiliency, Business Data Cloud, integration, SIEM/SOAR, and SuccessFactors
- **10 reference sheets** with the exact Horizon hex values, Helvetica typography hierarchy, shape / edge style strings, canvas layout, do-and-don't rules, corpus findings, generation-quality checklist, external-corpus guidance, researched improvement options, and the comparison methodology — every value cited from the [SAP BTP Solution Diagram Guidelines](https://sap.github.io/btp-solution-diagrams/) or observed in SAP's public corpus
- **A validator** (`validate.py`) that catches bent arrows, clipped labels, off-palette colors, off-grid coordinates, duplicate ids, missing `labelBackgroundColor`, and XML comments
- **An autofixer** (`autofix.py`) that mechanically repairs grid snap, hex case, missing `absoluteArcSize=1`, wrong `strokeWidth`, non-Helvetica fonts, and stray XML comments
- **A metadata-aware template selector + comparison harness** (`select_reference.py`, `compare.py`, `score_corpus.py`) that picks the nearest SAP template, fingerprints a `.drawio`, and reports a 0-100 fidelity score — the empirical justification for the "always start from a template" workflow

> **Why a dedicated skill?** Reproducing SAP Architecture Center style by hand or via a generic drawio skill consistently produces off-style output — wrong palette, bent `orthogonalEdgeStyle` arrows, clipped labels, text bleeding into `#EBF8FF` BTP fills, blank icon stencils (`shape=mxgraph.sap.icon;SAPIcon=…` doesn't render in many installs). This plugin bakes in the rules that matter and gates every output behind a validator.

## Table of contents

- [Quick start — Claude Code users](#quick-start--claude-code-users)
- [Install in Claude Desktop / Claude.ai](#install-in-claude-desktop--claudeai)
- [Use outside of Claude (other Agent-Skills runtimes)](#use-outside-of-claude-other-agent-skills-runtimes)
- [Use the scripts directly (no LLM)](#use-the-scripts-directly-no-llm)
- [What the skill does — workflow](#what-the-skill-does--workflow)
- [Design rules the skill enforces](#design-rules-the-skill-enforces)
- [Repo layout](#repo-layout)
- [Development](#development)
- [License & attribution](#license--attribution)
- [Credits & research sources](#credits--research-sources)

---

## Quick start — Claude Code users

In Claude Code:

```
/plugin marketplace add marianfoo/btp-drawio-skill
/plugin install sap-architecture
```

Then describe the diagram:

> Create an SAP architecture diagram showing a Copilot Studio MCP client calling an ARC-1 BTP Cloud Foundry app. ARC-1 authenticates via XSUAA OAuth, uses Destination Service + Cloud Connector with Principal Propagation to reach an on-prem S/4HANA system.

Claude will auto-load the skill (its trigger phrases are tuned for SAP / BTP / architecture / drawio keywords), run `select_reference.py`, pick the closest reference template, drop the right icons, compose the XML, run `autofix.py` + `validate.py` + `score_corpus.py`, and hand you back a ready-to-open `.drawio` file plus a numbered flow narration.

### Example prompts

- "Draw my BTP deployment — CAP app with XSUAA, HANA Cloud, Destination Service to on-prem ECC."
- "Diagram the XSUAA OAuth flow between Claude Desktop, our MCP server, and on-prem ABAP."
- "Show how a user on VS Code Copilot reaches SAP BW/4HANA through Cloud Connector with Principal Propagation."
- "Make an L1 conceptual diagram of a Joule integration with Task Center pulling from S/4, SuccessFactors, and Ariba."
- "Generate an L2 ref-arch for SAP Build Apps fronting a CAP service bound to SAP Event Mesh."

### Updating the plugin

```
/plugin update sap-architecture
```

### Uninstalling

```
/plugin uninstall sap-architecture
/plugin marketplace remove btp-drawio-skill
```

---

## Install in Claude Desktop / Claude.ai

Claude Desktop and Claude.ai load skills from the user's skills folder. Since this repo follows the [Agent Skills open standard](https://agentskills.io), you can drop the `SKILL.md` tree directly into the host's skills directory:

**macOS / Linux:**

```bash
git clone https://github.com/marianfoo/btp-drawio-skill.git
mkdir -p ~/.claude/skills
cp -R btp-drawio-skill/plugins/sap-architecture/skills/sap-architecture \
      ~/.claude/skills/
```

**Windows (PowerShell):**

```powershell
git clone https://github.com/marianfoo/btp-drawio-skill.git
New-Item -ItemType Directory -Force "$HOME\.claude\skills"
Copy-Item -Recurse `
  btp-drawio-skill\plugins\sap-architecture\skills\sap-architecture `
  "$HOME\.claude\skills\"
```

Restart Claude. The skill shows up in the Skills panel; Claude will auto-invoke it when you describe an SAP architecture. You still need **Python 3.8+** on `$PATH` for `validate.py` / `autofix.py` to run.

---

## Use outside of Claude (other Agent-Skills runtimes)

The skill is a plain [Agent Skills](https://agentskills.io)-compliant bundle — the `SKILL.md` frontmatter sticks to the portable subset (`name`, `description`) and doesn't depend on any Claude Code-specific feature. Anything that loads an `SKILL.md` tree should work:

- **Cursor / Windsurf / Continue** — point their custom-rules / rules-directory setting at `plugins/sap-architecture/skills/sap-architecture/`.
- **Self-hosted MCP clients / Open Interpreter / any Agent-Skills runtime** — drop the folder into the skills directory your client expects (check your client's docs for the path; `~/.agents/skills/` and `~/.config/<client>/skills/` are common).
- **Raw prompt** — concatenate `SKILL.md` + the `references/*.md` you need into the system prompt.

### Recommended minimal prompt if your host doesn't load skill files

```
You have access to the SAP Architecture Skill. When the user asks for an SAP /
BTP / on-prem architecture diagram, follow the 6-step workflow in SKILL.md:

1. Parse description → plan (L0/L1/L2, zones, services, flow, accent)
2. ALWAYS scaffold from a SAP reference template (NEVER write XML from scratch):
     scripts/scaffold_diagram.py "<request>" --out <destination>.drawio
3. Place BTP service icons via scripts/extract_icon.py / extract_asset.py
4. Make surgical label edits — do NOT rewrite the file. Preserve canvas size,
   zone hierarchy, network divider, SAP logos, footer, and identity flow.
5. MANDATORY: run scripts/autofix.py --write <file>, scripts/validate.py
   <file>, and scripts/score_corpus.py --min-score 90 <file>
6. Print the flow narration as a numbered markdown list

Hard rules enforced by the validator: no dark page backgrounds; flow pills must
use canonical SAP verbs (TRUST/Authenticate/Authorization/A2A/MCP/ORD/HTTPS/
OData/REST/SAML2/OIDC); preserve grey-circle icons; trust=pink, auth=green,
authorization=indigo, firewalls=thick grey; 16-px corner radius.
```

---

## Use the scripts directly (no LLM)

The plugin's Python scripts have zero third-party dependencies (stdlib only) and are useful on their own.

### List all available BTP icons

```bash
python3 plugins/sap-architecture/skills/sap-architecture/scripts/extract_icon.py --list
# → 100 icons, one per line: slug + display name
```

### Generate a ready-to-paste `<mxCell>` for a service icon

```bash
python3 plugins/sap-architecture/skills/sap-architecture/scripts/extract_icon.py \
  "Destination Service" \
  --x 600 --y 300 --w 80 --h 96 \
  --id svc-dest --parent 1
```

Fuzzy matching is built in — `"XSUAA"`, `"CPI"`, `"HANA"`, `"Cloud Connector"`, `"Audit Log"`, `"Authorization and Trust"` all resolve correctly.

### List or extract any SAP starter-kit asset

```bash
python3 plugins/sap-architecture/skills/sap-architecture/scripts/extract_asset.py --list --kind connector

python3 plugins/sap-architecture/skills/sap-architecture/scripts/extract_asset.py \
  "direct one-directional" \
  --kind connector \
  --x 200 --y 300 \
  --id flow1

python3 plugins/sap-architecture/skills/sap-architecture/scripts/extract_asset.py \
  "devices non sap" \
  --kind generic-icon \
  --x 100 --y 200 \
  --id generic-devices
```

`extract_asset.py` reads `assets/asset-index.json`, which covers all bundled SAP draw.io starter-kit libraries, not only BTP service icons. Use it for generic icons, connector presets, area/default shapes, essential shapes, number bubbles, SAP brand-name text, text styles, and interface/annotation pills.

### Pick the closest SAP template from a prompt

```bash
python3 plugins/sap-architecture/skills/sap-architecture/scripts/select_reference.py --top 5 \
  "Joule agent calls S/4HANA through MCP and XSUAA"
```

The selector ranks the 63 bundled templates by curated scenario metadata, family, level, filename matches, visible labels in the draw.io file, and strong aliases such as `DevOps`, `Edge Integration Cell`, `Federated ML`, `SuccessFactors`, `Joule`, `MCP`, and `Private Link`. Use it before editing XML.

### Score a diagram against a SAP reference

```bash
python3 plugins/sap-architecture/skills/sap-architecture/scripts/compare.py \
  plugins/sap-architecture/skills/sap-architecture/assets/reference-examples/btp_SAP_Cloud_Identity_Services_Authentication_L2.drawio \
  my-diagram.drawio

# one-line score 0-100
python3 plugins/sap-architecture/skills/sap-architecture/scripts/compare.py --score \
  reference.drawio my-diagram.drawio
```

Calibration: a hand-crafted candidate built from scratch typically scores 50-55. A candidate built by copying a SAP reference template + relabeling for your scenario scores roughly 95-100 structurally, while visible label/content drift now lowers the target score. See [`references/methodology.md`](plugins/sap-architecture/skills/sap-architecture/references/methodology.md) for the full breakdown.

### Score a diagram against the whole bundled corpus

```bash
python3 plugins/sap-architecture/skills/sap-architecture/scripts/score_corpus.py \
  --top 5 --min-score 90 my-diagram.drawio
```

`score_corpus.py` compares the candidate against all bundled SAP references and exits nonzero if the best score is below the threshold. For deeper research loops, pass cloned SAP repos with `--references /path/to/SAP/architecture-center --references /path/to/SAP/btp-solution-diagrams`.

### Run an Ollama-backed corpus evaluation loop

`eval_corpus.py` orchestrates the longer feedback loop: inventory SAP references, extract diagram descriptions, ask a local model for a generation plan, create candidates, run `autofix.py` + `validate.py`, score against the specific target reference and the whole corpus, and write reports under `.cache/sap-architecture-eval/`. The default pass mode is target-aware; corpus-only scoring is still available with `--pass-mode corpus`.

When `--exclude-target-template` is used, the harness now adds explicit "visual fallback" hints computed from the target reference fingerprint. That means the exact target cannot be copied, but the selected starting template is the closest available SAP layout. Add `--no-style-neighbor-hints` if you want a stricter pure-semantic leave-one-out selector test.

The report now separates `near-miss` cases from `ceiling-limited` cases. Near misses are worth retrying; ceiling-limited cases need better sibling templates or geometry-aware generation because the selected alternate SAP layout is already too far below the target. The default `--retry-margin 8` only retries cases scoring 82+ when `--min-score 90`, which avoids wasting long Ollama runs on structurally impossible cases. Use `--retry-margin 100` only when you deliberately want the old exhaustive behavior.

After a full run, focus only on the cases that can still benefit from more model attempts:

```bash
python3 plugins/sap-architecture/skills/sap-architecture/scripts/eval_corpus.py dry-run \
  --from-run .cache/sap-architecture-eval/<run-id> \
  --case-class near-miss \
  --generator ollama \
  --model qwen3.6:35b-a3b-nvfp4 \
  --exclude-target-template \
  --apply-model-plan
```

Use `--case-id <substring>` for manual family tests, for example `--case-id ra0024`, `--case-id agenticai`, or `--case-id cloudconnector`.

Fast smoke checks:

```bash
python3 -m py_compile plugins/sap-architecture/skills/sap-architecture/scripts/*.py

python3 plugins/sap-architecture/skills/sap-architecture/scripts/eval_corpus.py inventory

python3 plugins/sap-architecture/skills/sap-architecture/scripts/eval_corpus.py describe \
  --limit 3

python3 plugins/sap-architecture/skills/sap-architecture/scripts/eval_corpus.py dry-run \
  --limit 3 --generator ollama --model qwen3.6:35b-a3b-nvfp4
```

Create one diagram directly from a description:

```bash
python3 plugins/sap-architecture/skills/sap-architecture/scripts/eval_corpus.py create \
  --generator ollama \
  --model qwen3.6:35b-a3b-nvfp4 \
  --apply-model-plan \
  --out-file .cache/my-sap-diagram.drawio \
  "Create an L2 SAP BTP diagram for ..."
```

One-case Ollama smoke:

```bash
python3 plugins/sap-architecture/skills/sap-architecture/scripts/eval_corpus.py run \
  --limit 1 \
  --generator ollama \
  --model qwen3.6:35b-a3b-nvfp4 \
  --max-attempts 1 \
  --min-score 90
```

Leave-one-out smoke, where the harness may not copy the target diagram and uses the closest alternate SAP visual neighbor:

```bash
python3 plugins/sap-architecture/skills/sap-architecture/scripts/eval_corpus.py run \
  --limit 3 \
  --generator ollama \
  --model qwen3.6:35b-a3b-nvfp4 \
  --exclude-target-template \
  --apply-model-plan \
  --max-attempts 1 \
  --retry-margin 8 \
  --min-score 90 \
  --continue-on-error
```

Pure semantic leave-one-out, without target-derived visual-neighbor hints:

```bash
python3 plugins/sap-architecture/skills/sap-architecture/scripts/eval_corpus.py run \
  --limit 3 \
  --generator baseline \
  --exclude-target-template \
  --no-style-neighbor-hints \
  --max-attempts 1 \
  --retry-margin 8 \
  --min-score 90 \
  --continue-on-error
```

Long runs are opt-in:

```bash
python3 plugins/sap-architecture/skills/sap-architecture/scripts/eval_corpus.py run \
  --generator ollama \
  --model qwen3.6:35b-a3b-nvfp4 \
  --exclude-target-template \
  --apply-model-plan \
  --max-attempts 3 \
  --retry-margin 8 \
  --min-score 90 \
  --timeout-seconds 1200 \
  --continue-on-error
```

Focused near-miss retry after a previous run:

```bash
python3 plugins/sap-architecture/skills/sap-architecture/scripts/eval_corpus.py run \
  --from-run .cache/sap-architecture-eval/<run-id> \
  --case-class near-miss \
  --generator ollama \
  --model qwen3.6:35b-a3b-nvfp4 \
  --exclude-target-template \
  --apply-model-plan \
  --max-attempts 5 \
  --retry-margin 100 \
  --min-score 90 \
  --timeout-seconds 1200 \
  --continue-on-error
```

Generated candidates, raw model output, `summary.json`, and `report.md` are written below `.cache/` and are intentionally untracked. Curate any useful examples into the repo only after reviewing them.

Optional external SAP corpus: clone [`SAP/sap-btp-reference-architectures`](https://github.com/SAP/sap-btp-reference-architectures) under `.cache/external/` and run `eval_corpus.py --references .cache/external/sap-btp-reference-architectures ...` after the bundled run. That Apache-2.0 repository adds 32 editable `.drawio` test targets, including older BTP reference architectures that are intentionally harder than the bundled corpus. See [`references/external-test-corpus.md`](plugins/sap-architecture/skills/sap-architecture/references/external-test-corpus.md).

### Validate an existing `.drawio`

```bash
python3 plugins/sap-architecture/skills/sap-architecture/scripts/validate.py my-diagram.drawio

# strict mode — warnings become errors (exit 1)
python3 plugins/sap-architecture/skills/sap-architecture/scripts/validate.py --strict my-diagram.drawio

# machine-readable report (JSON on stdout)
python3 plugins/sap-architecture/skills/sap-architecture/scripts/validate.py --json my-diagram.drawio
```

The validator catches:

| Check | Level |
|---|---|
| Malformed XML, duplicate ids, missing `mxGeometry` | error |
| XML comments (`<!-- -->`) inside the mxfile | error |
| Bent orthogonal edges (source/target centers not aligned on any axis) | error |
| Label text wider than its shape (overflow / clipping) | error |
| Sibling shape overlap (not contained, not transparent, not pill) | error |
| Coordinates not on the 10-px grid | warning |
| `arcSize` without `absoluteArcSize=1` | warning |
| `strokeWidth` not in `{1, 1.5, 2, 3, 4}` | warning |
| `fontFamily` ≠ Helvetica | warning |
| Edge label missing `labelBackgroundColor=default` | warning |
| Hex color outside the SAP Horizon palette | warning |

### Autofix mechanical issues

```bash
python3 plugins/sap-architecture/skills/sap-architecture/scripts/autofix.py --write my-diagram.drawio
# writes in place with my-diagram.drawio.bak backup
```

Autofix automatically repairs: grid snapping, hex case, missing `absoluteArcSize=1`, `strokeWidth` rounding to `{1, 1.5, 2, 3, 4}`, non-Helvetica fonts.

### Regenerate the asset indexes

After refreshing bundled SAP libraries:

```bash
python3 plugins/sap-architecture/skills/sap-architecture/scripts/build_icon_index.py
python3 plugins/sap-architecture/skills/sap-architecture/scripts/build_asset_index.py
python3 plugins/sap-architecture/skills/sap-architecture/scripts/check_asset_coverage.py
```

---

## What the skill does — workflow

The skill is an **authoring assistant**, not a one-shot generator. The realistic workflow takes 15-30 min per diagram; ~⅓ of scenarios pass the corpus loop without manual editing, the remaining ⅔ need surgical edits in draw.io desktop. See [`references/manual-workflow.md`](plugins/sap-architecture/skills/sap-architecture/references/manual-workflow.md) for the time-budget table and the full loop.

When triggered, the skill runs a 6-step pipeline (documented in full in [`plugins/sap-architecture/skills/sap-architecture/SKILL.md`](plugins/sap-architecture/skills/sap-architecture/SKILL.md)):

1. **Parse → plan** — infer level (L0/L1/L2, default L2), zones, services, numbered flow steps, and which service is the "star" (accent color).
2. **Scaffold from a SAP reference template — MANDATORY** — run `scaffold_diagram.py "<request>" --out <file>.drawio`. The script ranks the 63 bundled SAP templates against the request, copies the best match to the destination, and prints alternates. The single most common cause of bad diagrams is the LLM trying to write XML from scratch — `scaffold_diagram.py` removes that temptation. Use `template_browser.py` (pre-rendered thumbnail gallery of all 63) when picking visually is faster than reading filenames.
3. **Place BTP service icons** — fuzzy-lookup each service via `extract_icon.py`, which emits an `<mxCell>` with the official inline-SVG data URI and grid-snapped geometry.
4. **Surgical relabel** — change labels, swap services, add a few cards next to the existing ones. **Preserve canvas size, zone hierarchy, network divider, SAP logos, footer, and identity flow.** For complex scenarios that need more than relabeling, open the file in draw.io desktop and edit directly. Reference docs: `references/layout.md`, `palette-and-typography.md`, `shapes-and-edges.md`, `do-and-dont.md`, `manual-workflow.md`.
5. **Validate, autofix, score — mandatory** — `autofix.py --write` first (mechanical repairs), then `validate.py` (now catches dark page backgrounds, novelty pill verbs like PROMPT/ROUTE/CONTEXT/DELEGATE, multi-logo over-use), then `score_corpus.py --min-score 90`.
5b. **Visual review (the missing last 20%)** — `render_compare.py <ref>.drawio <cand>.drawio --open` builds an HTML page with side-by-side rendered PNGs, structural score breakdown, and **actionable suggestions mapped to the lowest-scoring fingerprint dimensions**. The fingerprint score is necessary but insufficient; the visual review catches what XML diffing can't.
6. **Narrate the flow** — print a numbered list explaining what each pill means, for pasting below the embedded image in Markdown / Confluence.

---

## Design rules the skill enforces

Every rule is citable back to the SAP upstream. The skill never improvises palette values or style strings.

| Rule | Value | Source |
|---|---|---|
| **Primary SAP/BTP area** | stroke `#0070F2`, fill `#EBF8FF` | [foundation.md](https://github.com/SAP/btp-solution-diagrams/blob/main/guideline/docs/btp_guideline/foundation.md) |
| **Non-SAP area** | stroke `#475E75`, fill `#F5F6F7` | [foundation.md](https://github.com/SAP/btp-solution-diagrams/blob/main/guideline/docs/btp_guideline/foundation.md) |
| **Positive semantic** | stroke `#188918`, fill `#F5FAE5` | [foundation.md](https://github.com/SAP/btp-solution-diagrams/blob/main/guideline/docs/btp_guideline/foundation.md) |
| **Accent — indigo (authorization)** | stroke `#5D36FF`, fill `#F1ECFF` | [foundation.md](https://github.com/SAP/btp-solution-diagrams/blob/main/guideline/docs/btp_guideline/foundation.md) |
| **Accent — pink (trust)** | stroke `#CC00DC`, fill `#FFF0FA` | [foundation.md](https://github.com/SAP/btp-solution-diagrams/blob/main/guideline/docs/btp_guideline/foundation.md) |
| **Accent — teal (MCP / emphasis)** | stroke `#07838F`, fill `#DAFDF5` | [foundation.md](https://github.com/SAP/btp-solution-diagrams/blob/main/guideline/docs/btp_guideline/foundation.md) |
| **Corner radius** | fixed 16 px (`arcSize=16;absoluteArcSize=1`) | [areas.md](https://github.com/SAP/btp-solution-diagrams/blob/main/guideline/docs/btp_guideline/diagr_comp/areas.md) |
| **Nested areas** | alternate fill / no-fill for contrast; parent is the BTP layer | [areas.md](https://github.com/SAP/btp-solution-diagrams/blob/main/guideline/docs/btp_guideline/diagr_comp/areas.md) |
| **Icons** | grey-background-circle variant only — *mandatory for diagram visualization* | [icons.md](https://github.com/SAP/btp-solution-diagrams/blob/main/guideline/docs/btp_guideline/diagr_comp/icons.md) |
| **Trust flows** | pink | [lines_connectors.md](https://github.com/SAP/btp-solution-diagrams/blob/main/guideline/docs/btp_guideline/diagr_comp/lines_connectors.md) |
| **Authentication flows** | green | [lines_connectors.md](https://github.com/SAP/btp-solution-diagrams/blob/main/guideline/docs/btp_guideline/diagr_comp/lines_connectors.md) |
| **Authorization flows** | indigo | [lines_connectors.md](https://github.com/SAP/btp-solution-diagrams/blob/main/guideline/docs/btp_guideline/diagr_comp/lines_connectors.md) |
| **Firewalls / network barriers** | thick grey (`strokeWidth=3` or `4`) | [lines_connectors.md](https://github.com/SAP/btp-solution-diagrams/blob/main/guideline/docs/btp_guideline/diagr_comp/lines_connectors.md) |
| **Line styles** | solid = sync request/response; dashed = async; dotted = optional; thick = firewall only | [foundation.md](https://github.com/SAP/btp-solution-diagrams/blob/main/guideline/docs/btp_guideline/foundation.md) |
| **Spacing** | even, ~height of the SAP logo | [foundation.md](https://github.com/SAP/btp-solution-diagrams/blob/main/guideline/docs/btp_guideline/foundation.md) |
| **Legend** | mandatory in each diagram | [foundation.md](https://github.com/SAP/btp-solution-diagrams/blob/main/guideline/docs/btp_guideline/foundation.md) |

Conventions this skill adds on top of the SAP upstream (none of which are prescribed by SAP, but all are accepted defaults across the community — [lemaiwo/btp-drawio-skill](https://github.com/lemaiwo/btp-drawio-skill), [miyasuta/claude-drawio-btp-diagram](https://github.com/miyasuta/claude-drawio-btp-diagram)):

- **Canvas**: preserve the selected SAP template size; default new L2 diagrams to 1169 × 827 px (A4 landscape)
- **Grid**: 10 px, everything snapped
- **Font**: Helvetica (draw.io-portable; SAP products use "72")
- **L0 / L1 / L2** — the level taxonomy documented by SAP's BTP Solution Diagram Guidelines. Default is **L2** (technical stakeholders, services + auth flows + legend). See [`references/levels.md`](plugins/sap-architecture/skills/sap-architecture/references/levels.md).

### How the validator helps

Compared with the generic "eyeball it" approach, the validator catches classes of bug an LLM can't reliably self-police:

- **Bent arrows** — an `orthogonalEdgeStyle` edge between A and B only renders straight if `A.centerX == B.centerX` OR `A.centerY == B.centerY`. Off-by-5-px → visible 90° kink. This single rule (credit: [miyasuta/claude-drawio-btp-diagram](https://github.com/miyasuta/claude-drawio-btp-diagram)) is the highest-leverage polish trick in the whole pipeline.
- **Label overflow** — `whiteSpace=wrap;html=1` labels are checked word-by-word; non-wrap labels are checked full-string. Prevents the "my pill says 'OAUT'" bug.
- **Missing `labelBackgroundColor=default`** — without it, edge label text bleeds into the `#EBF8FF` BTP zone fill and becomes unreadable.
- **Off-grid coordinates** — draw.io's UI loves emitting `239.9999999...` after a nudge. Autofix quantises them.
- **`arcSize` without `absoluteArcSize=1`** — a 16 without absolute treats 16 as *percent*, so a 700-px-wide zone gets a 112-px corner radius.

---

## Repo layout

```
btp-drawio-skill/
├── README.md                              ← you are here
├── LICENSE                                ← MIT (plugin code)
├── .gitignore
├── .claude-plugin/
│   └── marketplace.json                   ← single-plugin marketplace catalog
└── plugins/
    └── sap-architecture/
        ├── .claude-plugin/
        │   └── plugin.json
        ├── README.md                      ← plugin-level deep dive
        └── skills/
            └── sap-architecture/
                ├── SKILL.md               ← 6-step workflow (<500 lines)
                ├── references/
                │   ├── levels.md          ← L0/L1/L2 decision guide
                │   ├── palette-and-typography.md  ← Horizon hex + Helvetica + SAP rules
                │   ├── shapes-and-edges.md ← style strings + line semantics
                │   ├── layout.md          ← canvas + zone-by-zone placement
                │   ├── do-and-dont.md     ← consolidated SAP rules (verbatim quotes)
                │   ├── corpus-findings.md ← 2026 SAP corpus profile
                │   ├── generation-quality.md ← research-backed output checklist
                │   ├── external-test-corpus.md ← optional external SAP corpus
                │   ├── improvement-options.md ← researched ranking of next improvements
                │   └── methodology.md     ← comparison harness, fidelity claim
                ├── assets/
                │   ├── libraries/         ← 10 SAP draw.io libraries (Apache-2.0)
                │   ├── reference-examples/ ← 63 pristine SAP templates (Apache-2.0)
                │   │   └── template-metadata.json ← curated selector aliases/tags
                │   ├── icon-index.json    ← pre-computed slug→mxCell style lookup
                │   ├── asset-index.json   ← 448 searchable SAP starter-kit assets
                │   └── NOTICE.md          ← per-file Apache-2.0 attribution
                ├── examples/
                │   └── iam-arc1-mcp-l2.drawio  ← worked example (96.6 vs source; 100 self-check)
                └── scripts/
                    ├── build_icon_index.py
                    ├── build_asset_index.py
                    ├── extract_icon.py
                    ├── extract_asset.py
                    ├── check_asset_coverage.py
                    ├── validate.py
                    ├── autofix.py
                    ├── select_reference.py
                    ├── compare.py         ← pairwise fingerprint score
                    ├── score_corpus.py    ← best score across reference corpus
                    └── eval_corpus.py     ← Ollama-ready corpus evaluation loop
```

---

## Development

### Testing the plugin locally before publishing

```bash
git clone https://github.com/marianfoo/btp-drawio-skill.git
cd btp-drawio-skill

# Option A: load directly into your Claude Code session
claude --plugin-dir ./plugins/sap-architecture

# Option B: register this checkout as a local marketplace
# (in Claude Code)
/plugin marketplace add ./
/plugin install sap-architecture
```

### Running the validator in CI

```yaml
# .github/workflows/validate-diagrams.yml
- name: Validate SAP architecture diagrams
  run: |
    for f in docs/**/*.drawio; do
      python3 plugins/sap-architecture/skills/sap-architecture/scripts/autofix.py "$f"
      python3 plugins/sap-architecture/skills/sap-architecture/scripts/validate.py "$f"
      python3 plugins/sap-architecture/skills/sap-architecture/scripts/score_corpus.py --min-score 90 "$f"
    done
```

### Regenerating the asset indexes

After refreshing `assets/libraries/*.xml` from the SAP upstream:

```bash
python3 plugins/sap-architecture/skills/sap-architecture/scripts/build_icon_index.py
python3 plugins/sap-architecture/skills/sap-architecture/scripts/build_asset_index.py
python3 plugins/sap-architecture/skills/sap-architecture/scripts/check_asset_coverage.py
```

---

## License & attribution

- **Plugin code** (Python scripts, markdown references, plugin manifests, this README): MIT — see [LICENSE](LICENSE).
- **Bundled SAP assets** under `plugins/sap-architecture/skills/sap-architecture/assets/` (icon library + reference templates): **Apache-2.0**, © SAP SE or an SAP affiliate company — sourced from [`SAP/btp-solution-diagrams`](https://github.com/SAP/btp-solution-diagrams) and [`SAP/architecture-center`](https://github.com/SAP/architecture-center). See `plugins/sap-architecture/skills/sap-architecture/assets/NOTICE.md` for full attribution.

---

## Credits & research sources

The skill's conventions were cross-referenced from the following sources, each cited inline in the design-rules table above:

**SAP upstream — the canonical rules:**
- [architecture.learning.sap.com](https://architecture.learning.sap.com/) — SAP Architecture Center
- [`SAP/architecture-center`](https://github.com/SAP/architecture-center) — source `.drawio` files for published ref-archs
- [`SAP/btp-solution-diagrams`](https://github.com/SAP/btp-solution-diagrams) — the official design system (Atomic model, Horizon palette, line / icon / connector rules)
- [SAP BTP Solution Diagram Guidelines site](https://sap.github.io/btp-solution-diagrams/)

**Prior art — community skills that informed this one:**
- [`miyasuta/claude-drawio-btp-diagram`](https://github.com/miyasuta/claude-drawio-btp-diagram) — the center-alignment rule for straight orthogonal edges; the `docs/rules + docs/styles + docs/GUIDELINES.md` layering pattern
- [`lemaiwo/btp-drawio-skill`](https://github.com/lemaiwo/btp-drawio-skill) — the marketplace + single-plugin repo layout used here; the approach of bundling SAP icon XML libraries directly

**Claude Code plugin + skills docs:**
- [Claude Code plugins](https://docs.claude.com/en/docs/claude-code/plugins)
- [Plugin marketplaces](https://docs.claude.com/en/docs/claude-code/plugin-marketplaces)
- [Skills](https://docs.claude.com/en/docs/claude-code/skills)
- [Plugins reference](https://docs.claude.com/en/docs/claude-code/plugins-reference)
- [Agent Skills open standard](https://agentskills.io)
