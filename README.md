# btp-drawio-skill

A Claude Code plugin (and Agent-Skill-compatible standalone skill) that turns a plain-English description into a polished **SAP Architecture Center / BTP solution diagram** as an editable `.drawio` file — following the **official SAP BTP Solution Diagram Guidelines**.

> **Why a dedicated skill?** Reproducing SAP Architecture Center style by hand or via a generic drawio skill consistently produces off-style output — wrong palette, bent arrows, clipped labels, text bleeding into BTP fills, blank icon stencils. This plugin bakes in the rules that matter and gates every output behind a validator.

Under the hood it bundles **100 SAP BTP service icons, 71 reference templates, 448 indexed draw.io assets, a validator, and an autofixer** — all local, all traceable to SAP's guidelines.

## Table of contents

- [Install](#install)
- [Recommended models](#recommended-models)
- [Use it](#use-it)
- [Write better prompts](#write-better-prompts)
- [What's bundled](#whats-bundled)
- [How it works](#how-it-works)
- [Documentation & deep dive](#documentation--deep-dive)
- [License & credits](#license--attribution)

---

## Install

**Recommendation: install it as a skill — that's all you need.** It works the same way everywhere Claude Code runs — terminal, IDE extension, or the Claude desktop/web apps: install once, then describe the diagram in plain English and Claude auto-loads the skill. You do **not** need to build an `.mcpb` bundle or publish to npm — those are optional extras for non-Claude tools, documented in [internals](docs/internals.md#npx-mcp-and-mcpb-non-claude-tools).

### Claude Code (CLI)

```
/plugin marketplace add marianfoo/btp-drawio-skill
/plugin install sap-architecture
```

Update or remove later:

```
/plugin update sap-architecture
/plugin uninstall sap-architecture
/plugin marketplace remove btp-drawio-skill
```

### Other AI coding tools (VS Code Copilot, OpenAI Codex, Cursor, …)

You don't need Claude for this. The skill is **portable** — plain Markdown (`SKILL.md`) plus dependency-free Python scripts — so any agent that can read a project instructions file and run shell commands can drive it. Wire it in once, then ask for a diagram.

**First, get the skill files** where your agent can reach them:

```bash
git clone https://github.com/marianfoo/btp-drawio-skill.git
```

**Then point your tool's instruction file at the skill:**

| Tool | Add / use this file | Official docs |
|---|---|---|
| **OpenAI Codex** (CLI & IDE) | `AGENTS.md` in your repo root | [AGENTS.md](https://agents.md/) · [Codex guide](https://developers.openai.com/codex/guides/agents-md) |
| **GitHub Copilot** (VS Code, agent mode) | `.github/copilot-instructions.md` | [VS Code custom instructions](https://code.visualstudio.com/docs/agent-customization/custom-instructions) |
| **Cursor** | bundled [`cursor-rules/sap-architecture.mdc`](plugins/sap-architecture/cursor-rules/sap-architecture.mdc) → `.cursor/rules/` | [Cursor Rules](https://cursor.com/docs/rules) |
| **Gemini CLI · Jules · Amp · Factory** | `AGENTS.md` (same open standard) | [AGENTS.md](https://agents.md/) |
| **Windsurf · Cline · Continue · Aider** | that tool's rules / context file → point it at the skill folder | their own docs |
| **Anything else** | paste the skill's instructions into the system prompt | [ready-made prompt](docs/internals.md#use-outside-of-claude-other-agent-skills-runtimes) |

**And tell the agent to use it** — put something like this in that file (full version in [internals](docs/internals.md#use-outside-of-claude-other-agent-skills-runtimes)):

```markdown
For any SAP / BTP / on-prem architecture diagram, use the sap-architecture skill at
<skill-directory>. Resolve SKILL_DIR to the directory containing SKILL.md; do not assume
.claude, .codex, or the repository root. Follow the guarded workflow: lock a semantic
specification → scaffold and pin one SAP template → sanitize derivative provenance → edit
surgically → run strict semantic/provenance/structural gates → render candidate and target →
inspect both images → record the hash-bound visual review → rerun verify_delivery.py to PASS.
Never write .drawio XML from scratch and never preserve source QR/reference identifiers in a
modified diagram.
```

> **Two caveats:** unlike Claude, these tools won't *auto-load* the skill — the instruction file wires it in per project; and the agent needs shell access plus **Python 3.8+** to run the scripts. Use a strong model (see [Recommended models](#recommended-models)) — e.g. Codex with GPT-5.5; small models skip the scaffold/validate discipline.

> Want the skill in VS Code or JetBrains *with Claude* instead? The official [Claude Code extension](https://code.claude.com/docs/en/vs-code) runs it just like the CLI — install the extension, then `/plugins`.

### Claude Desktop / Claude.ai

These apps load skills from your skills folder. Since this repo follows the [Agent Skills open standard](https://agentskills.io), drop the skill tree straight in:

**macOS / Linux:**

```bash
git clone https://github.com/marianfoo/btp-drawio-skill.git
mkdir -p ~/.claude/skills
cp -R btp-drawio-skill/plugins/sap-architecture/skills/sap-architecture ~/.claude/skills/
```

**Windows (PowerShell):**

```powershell
git clone https://github.com/marianfoo/btp-drawio-skill.git
New-Item -ItemType Directory -Force "$HOME\.claude\skills"
Copy-Item -Recurse `
  btp-drawio-skill\plugins\sap-architecture\skills\sap-architecture `
  "$HOME\.claude\skills\"
```

Restart Claude — the skill shows up in the Skills panel and auto-invokes when you describe an SAP architecture.

### What you need

- **Claude Code or Claude Desktop / Claude.ai** — any recent version with skills support.
- **Python 3.8+ on your PATH** — the diagram engine (template selection, icon extraction, autofix, validation, scoring) is plain Python with zero third-party dependencies. Check with `python3 --version`.
- **draw.io to open the result** — the [desktop app](https://www.drawio.com/) or [app.diagrams.net](https://app.diagrams.net). Only needed to view/edit; the skill writes the `.drawio` without it.
- **The draw.io desktop CLI for completion** — an editable draft can be created without it, but the guarded final gate requires rendered candidate/reference images and a hash-bound visual review.
- **No API keys, no `npm install`, no MCP server, no cloud calls** — every icon, template, and script is bundled and runs locally.

---

## Recommended models

This is **not an easy task.** A good diagram needs multi-step reasoning — parse the scenario, pick the right SAP template, place icons, make surgical XML edits without breaking layout, then run the validate/score loop and react to the results. Use a strong frontier reasoning model:

| Tier | Models | Notes |
|---|---|---|
| **Best** | Claude **Opus 4.x** (e.g. Opus 4.8) | Top results; follows the scaffold-then-validate discipline reliably. In Claude Code, select it with `/model`. |
| **Also strong** | **GPT-5.5** / latest GPT-5-series, Google **Gemini 2.5 Pro** | Good choices in non-Claude runtimes (Cursor, Windsurf, …). |
| **Budget but capable** | Claude **Sonnet 4.x** | Faster/cheaper; usually fine for straightforward template-based diagrams. |
| **Avoid for authoring** | Haiku-class, `*-mini` / `*-nano`, small local models (<~30B) | They tend to skip the template scaffold and write XML from scratch, ignore the validate/score gate, and produce off-style output. |

> The local Ollama loop in [internals](docs/internals.md#ollama-backed-corpus-evaluation-loop) is a **separate batch-testing path** — it deliberately uses small local models to stress-test the corpus, not to author your real diagrams.

---

## Use it

Install the skill, then describe the architecture you want. The skill first converts that request into a semantic contract, selects and pins the closest reference template, marks the result as a derivative, applies surgical edits, and runs semantic, provenance, structural, pinned-template, rendering, and visual-review gates before reporting a final status.

A good first prompt:

> Create an SAP architecture diagram showing a Copilot Studio MCP client calling an ARC-1 BTP Cloud Foundry app. ARC-1 authenticates via XSUAA OAuth, uses Destination Service + Cloud Connector with Principal Propagation to reach an on-prem S/4HANA system.

### Example prompts

- "Draw my BTP deployment — CAP app with XSUAA, HANA Cloud, Destination Service to on-prem ECC."
- "Diagram the XSUAA OAuth flow between Claude Desktop, our MCP server, and on-prem ABAP."
- "Show how a user on VS Code Copilot reaches SAP BW/4HANA through Cloud Connector with Principal Propagation."
- "Make an L1 conceptual diagram of a Joule integration with Task Center pulling from S/4, SuccessFactors, and Ariba."
- "Generate an L2 ref-arch for SAP Build Apps fronting a CAP service bound to SAP Event Mesh."

For sharper results, see [Write better prompts](#write-better-prompts).

### Good to know (limits)

- **It's an authoring assistant, not a one-shot generator.** Budget ~15–30 min per diagram: roughly ⅓ of prompts pass the quality gate clean, the rest need a few surgical edits in draw.io desktop.
- **No Python → no quality gates.** Claude can still draft a diagram, but the validator/scorer won't run, so you lose the off-palette / bent-arrow / clipped-label checks.
- **No draw.io CLI means draft status only.** Rendering and visual inspection are mandatory before the guarded workflow can pass.
- **SAP / BTP / on-prem diagrams only.** It's tuned to the SAP Horizon style and a 71-template corpus, not a general-purpose diagram generator.
- **`npx btp-drawio-skill` is not the skill** and isn't published to npm yet — it's the raw CLI/MCP wrapper for non-Claude tools. Skip it for Claude.

### Nudge it to a good diagram

**Expect the first draft to be ~80% there, then nudge it.** The skill ships a feedback loop that closes the gap — when you ask Claude to keep improving, it renders the diagram to an image, scores it against the SAP corpus, *looks at the picture*, fixes one thing, and re-checks. So you can review the result and reply in plain English; you don't need to touch XML.

Give **specific, visual** feedback. Vague ("make it better") gives weak results; concrete observations map directly to fixes:

- "The icons are too large and overlap the card text — shrink them to SAP's 32×32." 
- "Two arrows cross straight through the BTP box — re-route them around it."
- "Joule should be its own purple zone next to BTP, not nested inside it."
- "The visual frame is incomplete — restore the template structure but keep the derivative attribution and remove stale source identifiers."
- "Use the canonical SAP flow pills (TRUST, Authenticate, OAuth, OData/REST), not invented labels."

Under the hood the agent runs `iterate.py` (render + score + the worst-first fix list) and `render_compare.py` (a side-by-side / overlay / swipe / difference HTML review you can open in a browser). You don't run these yourself — just describe what looks off and let it loop until the diagram matches the SAP reference. See [internals](docs/internals.md) for the loop details.

---

## Write better prompts

The skill works best when the prompt describes an architecture, not just a product list. Give the agent enough context to choose the right SAP reference template and preserve its structure.

Use this shape for high-quality prompts:

```text
Create an L2 SAP Architecture Center-style draw.io diagram for <scenario>.

Audience and level: <business overview | solution architecture | implementation flow>.
Main zones: <User/Client>, <SAP BTP subaccount/runtime>, <SAP Cloud Solutions>, <On-Premise>, <Third-party/Hyperscaler>, <Network divider if relevant>.
Actors and entry points: <who starts the flow and from where>.
SAP BTP services: <exact service names>.
Backends/systems: <SAP S/4HANA, ECC, BW/4HANA, SuccessFactors, Datasphere, Databricks, etc.>.
Identity/security: <IAS, XSUAA, OAuth, SAML, Principal Propagation, trust, authorization>.
Flow steps: 1. <protocol/action>, 2. <protocol/action>, 3. <protocol/action>.
Constraints: <must show Cloud Connector | use Joule as separate zone | prefer template RA0029 | avoid implementation internals>.
Output: editable .drawio plus numbered flow narration below the diagram.
```

Helpful context to attach or paste:

- Existing architecture notes, but trimmed to the services, actors, systems, and flows that should appear.
- A numbered flow, even if rough. Protocol words such as `HTTPS`, `OData/REST`, `OAuth`, `SAML`, `A2A`, `MCP`, `ORD`, and `Principal Propagation` help the skill pick canonical pills and edge colors.
- The intended abstraction level: `L0` for business overview, `L1` for solution components, `L2` for default technical flow. Avoid mixing all three in one diagram.
- The deployment boundary: which systems are inside SAP BTP, which are SAP cloud apps, which are on-premise, and which are third party or hyperscaler.
- Any preferred SAP reference/template name if you know it, for example `ac_RA0029_AgenticAI_root.drawio` for Agentic AI with Joule.
- A short list of exclusions, such as "do not show CI/CD" or "do not include database internals".

Avoid prompts like "make a BTP diagram for our app" unless you want the agent to ask a clarifying question. Also avoid dumping long unfiltered design docs: they usually contain several diagrams' worth of scope. If you paste a long document, add a short "diagram scope" paragraph that says exactly which flow to draw.

**Strong prompt:**

> Create an L2 SAP Architecture Center-style draw.io diagram. A developer in VS Code uses ARC-1 running on SAP BTP Cloud Foundry. ARC-1 authenticates with XSUAA, reads a Destination, uses SAP Connectivity service and SAP Cloud Connector, and calls on-premise SAP S/4HANA via OData/REST with Principal Propagation. Show zones for Developer Workstation, SAP BTP Cloud Foundry, and Customer On-Premise Network. Output editable `.drawio` and a numbered flow narration.

**Weak prompt:**

> Draw ARC-1 with BTP and S/4HANA.

---

## What's bundled

- **100 SAP BTP service icons** (inline SVG data URIs, grey-background-circle variant — the one [SAP mandates](https://github.com/SAP/btp-solution-diagrams/blob/main/guideline/docs/btp_guideline/diagr_comp/icons.md) for diagrams)
- **448 indexed SAP draw.io starter-kit assets** across 10 bundled libraries: BTP service icons, generic icons, connector presets, area/default shapes, essential shapes, number markers, SAP brand-name text, text elements, and annotation/interface pills
- **71 pristine reference templates** (Apache-2.0): canonical examples from [`SAP/btp-solution-diagrams`](https://github.com/SAP/btp-solution-diagrams), curated reference architectures from [`SAP/architecture-center`](https://github.com/SAP/architecture-center), and selected external SAP references — covering IAM, Joule, MCP / Agentic AI, multitenant SaaS, DevOps, Private Link, Cloud Connector, Event-Driven Architecture, resiliency, Business Data Cloud, integration, SIEM/SOAR, and SuccessFactors
- **12 reference sheets** covering semantic contracts, guarded provenance, Horizon values, typography, shapes/edges, layout, levels, manual iteration, and scoring methodology
- **A validator + autofixer** (`validate.py`, `autofix.py`) that catch and mechanically repair bent arrows, clipped labels, off-palette colors, off-grid coordinates, wrong stroke widths, non-Helvetica fonts, and more
- **A template selector + scoring harness** (`select_reference.py`, `compare.py`, `score_corpus.py`) that picks the nearest SAP template and reports how close a diagram is to the corpus
- **Guarded completion gates** (`validate_semantics.py`, `provenance.py`, `verify_delivery.py`, `record_visual_review.py`) that prevent a visually similar but request-incomplete diagram, stale official identifiers, new structural warnings, or an uninspected render from passing

Full palette/style rules and the scoring methodology live in [internals](docs/internals.md#design-rules-the-skill-enforces).

---

## How it works

The skill is an **authoring assistant**, not a one-shot generator. Its guarded pipeline is: lock a semantic specification → scaffold and pin the closest SAP reference template → mark and sanitize the derivative → make surgical edits → autofix → validate semantics and provenance → reject new structural warnings → score against the pinned template → render candidate and reference → inspect both → bind the review to the image hashes → narrate the flow. If visual review proves the selected template is an unrelated architecture family, the workflow rejects it and uses the constrained semantic fallback with zero warnings and SAP-likeness at least 90. The four proofs are independent: SAP-like appearance, XML validity, request coverage, and actual pixel review.

See the operational contract in **[`SKILL.md`](plugins/sap-architecture/skills/sap-architecture/SKILL.md)** and the design/scoring internals in **[docs/internals.md](docs/internals.md)**.

---

## Documentation & deep dive

- **[docs/internals.md](docs/internals.md)** — how it works (full pipeline), the SAP design rules it enforces, running the Python scripts yourself, npx / MCP / MCPB, other Agent-Skills runtimes, the Ollama evaluation loop, repo layout, and development.
- **[`SKILL.md`](plugins/sap-architecture/skills/sap-architecture/SKILL.md)** — the skill instructions Claude loads.
- **[`references/`](plugins/sap-architecture/skills/sap-architecture/references/)** — the cited reference sheets (palette, typography, shapes/edges, levels, layout, methodology).
- **[`plugins/sap-architecture/README.md`](plugins/sap-architecture/README.md)** — plugin-level deep dive.

---

## License & attribution

- **Plugin code** (Python scripts, markdown references, plugin manifests, this README): MIT — see [LICENSE](LICENSE).
- **Bundled SAP assets** under `plugins/sap-architecture/skills/sap-architecture/assets/` (icon library + reference templates): **Apache-2.0**, © SAP SE or an SAP affiliate company — sourced from [`SAP/btp-solution-diagrams`](https://github.com/SAP/btp-solution-diagrams), [`SAP/architecture-center`](https://github.com/SAP/architecture-center), and [`SAP/sap-btp-reference-architectures`](https://github.com/SAP/sap-btp-reference-architectures). See `plugins/sap-architecture/skills/sap-architecture/assets/NOTICE.md` and `plugins/sap-architecture/skills/sap-architecture/assets/source-manifest.json` for attribution, counts, file hashes, and source-revision limitations.

### Credits & research sources

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
