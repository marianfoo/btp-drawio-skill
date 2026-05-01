# The realistic SAP-diagram workflow

This skill is an **authoring assistant**, not a one-shot generator. After
weeks of iteration on the LLM-only loop, the leave-one-out evaluation
plateaus at ~22/63 passes (target score ≥ 90). 28 of the remaining 41
failures are *ceiling-limited*: the closest available SAP template is
geometrically too different from the target, and no amount of label
edits can close the gap. 13 are *near-miss* and improve modestly with
retries.

The honest conclusion: **producing a polished, SAP-Architecture-Center-
quality diagram requires manual editing for ~⅔ of scenarios.** That is
not a defect of the skill; it matches how SAP architects actually work.
The skill exists to make that manual loop as fast and disciplined as
possible.

## Why pure LLM generation hits a ceiling

| Stage | What's automatable | What requires human judgment |
|---|---|---|
| Template selection | yes — `select_reference.py` ranks 63 templates by metadata + visible labels | yes when the prompt is ambiguous or the right template isn't bundled |
| Label rewrites | yes — Ollama's safe label edits | semantic correctness ("does this XSUAA actually call that destination?") |
| Adding/removing services | partially — `extract_icon.py` drops the right icon at coordinates | layout decisions: which zone, where in the zone, what neighbours |
| Connector geometry | partially — autofix snaps to grid | alignment to anchor points, edge routing around other shapes |
| Visual polish | no | the last 20% of pixel-perfection |

The `compare.py` fingerprint score measures **structural style** (palette,
fonts, zone count, pill count, label tokens). It does not measure
**visual correctness** (Joule beside BTP vs nested inside BTP, network
divider drawn as a thick grey vertical line, footer band matching SAP's
template). For that you need to look at the rendered diagram.

## The fast manual loop (15-30 minutes per diagram)

```
1. plan       (~2 min)   describe scenario, level, zones, flow
2. scaffold   (~10 sec)  scaffold_diagram.py "<request>" --out file.drawio
3. inspect    (~1 min)   open template_browser/index.html if uncertain about choice
4. edit       (~10-20 min) open file.drawio in draw.io desktop, surgically relabel
5. validate   (~5 sec)   autofix.py --write && validate.py
6. compare    (~5 sec)   render_compare.py reference.drawio file.drawio --open
7. iterate    repeat 4-6 until visual review looks right
```

Each step has tooling support so the only attention-heavy part is step 4.

## Tools available for each step

### Step 1 — plan

Write the description in 5-10 lines: level (L0/L1/L2), zones (BTP,
On-Prem, Joule, Third-Party, Network divider, Cloud Solutions), services
in each zone, numbered flow with pill colors, accent app.

### Step 2 — scaffold (mandatory first action)

```bash
python3 scripts/scaffold_diagram.py \
  "<the user's full diagram request>" \
  --out docs/architecture/my-diagram.drawio
```

The script ranks the 63 bundled SAP templates against the request,
copies the best match to the destination, and prints the alternates.
Use `--template <filename>` to pin a specific template, `--dry-run` to
inspect candidates without copying, `--diagram-name "<title>"` to rename
the diagram page after copy.

### Step 3 — browse templates visually (optional)

```bash
python3 scripts/template_browser.py
open .cache/template-browser/index.html
```

Pre-renders all 63 templates into a clickable thumbnail grid with
filter, domain badges, and the `scaffold_diagram.py --template` command
for each. Useful when the selector is unsure or the prompt is vague.

### Step 4 — edit in draw.io desktop

Open the scaffolded file in draw.io desktop. Make these edits:

- **Title and subtitle** — match your scenario.
- **Service-card labels** — replace template's example service names with
  yours. Use exact SAP product names ("SAP S/4HANA Cloud", not
  "S/4HANA").
- **Icons** — swap or add via `scripts/extract_icon.py "Destination Service"
  --x 600 --y 300 --w 80 --h 96 --id svc-dest`.
- **Connectors** — adjust source/target if you swapped services. Keep
  the SAP-mandated colors: trust=#CC00DC pink, auth=#188918 green,
  authorization=#5D36FF indigo, structural=#475E75 slate.
- **Pills** — relabel from the canonical SAP vocabulary
  (TRUST/Authenticate/Authorization/A2A/MCP/ORD/HTTPS/OData/REST/...). 
  Avoid novelty verbs like PROMPT/ROUTE/CONTEXT/DELEGATE.

**Do NOT touch:** canvas size, zone hierarchy, network divider, SAP
logos, footer band, identity flow placement. Those carry the SAP visual
identity; preserving them is what keeps the score above 90.

### Step 5 — autofix + validate

```bash
python3 scripts/autofix.py --write docs/architecture/my-diagram.drawio
python3 scripts/validate.py docs/architecture/my-diagram.drawio
```

Autofix repairs the mechanical issues (grid snap, hex case, missing
`absoluteArcSize=1`, wrong `strokeWidth`, non-Helvetica fonts, XML
comments). Validate catches the rest (bent arrows, label overflow,
sibling overlap, edge labels missing `labelBackgroundColor`,
*off-vocabulary pill verbs, dark page backgrounds, multi-logo
over-use*).

### Step 6 — render and side-by-side compare

```bash
python3 scripts/render_compare.py \
  assets/reference-examples/ac_RA0029_AgenticAI_root.drawio \
  docs/architecture/my-diagram.drawio \
  --out-dir .cache/review/agentic-ai/ \
  --open
```

Outputs `review.html` with reference + candidate rendered side by side,
score breakdown, and **actionable suggestions mapped to the lowest-
scoring fingerprint dimensions**. Open it in the browser. The visual
review surfaces what the structural fingerprint can't.

### Step 7 — corpus score

```bash
python3 scripts/score_corpus.py --min-score 90 docs/architecture/my-diagram.drawio
```

Final gate: the candidate must score ≥ 90 against at least one bundled
SAP reference. If lower, look at the `render_compare.py` review HTML
and address the suggestions.

## When manual editing is *not* needed

A few scenarios pass the loop on the first scaffold, no editing
required:

| Scenario | Template that wins | Why |
|---|---|---|
| Generic Agentic AI on BTP | `ac_RA0029_AgenticAI_root.drawio` | Joule + BTP + Cloud Solutions structure already present |
| Task Center central inbox | `btp_SAP_Task_Center_L2.drawio` | Canonical layout |
| OData via App Router + Private Link | `ac_RA0014_OData_AppRouter_PrivateLink.drawio` | Specific RA, narrow scenario |
| SAP IAS authentication L2 | `btp_SAP_Cloud_Identity_Services_Authentication_L2.drawio` | Direct match |

For these, scaffold + run the validators is enough. ~22/63 of leave-one-out
evals already pass at this level. Run

```bash
python3 scripts/eval_corpus.py inventory --references assets/reference-examples
```

to see the full bundled list.

## When manual editing *is* needed (and how much)

- **ceiling-limited families** — RA0027 SIEM/SOAR/ETD, RA0028
  SuccessFactors module integration, RA0013 BDC AI Core, RA0023 DevOps,
  RA0029 Embodied AI Agents. Expect 15-30 min of manual editing per
  diagram unless you're willing to bundle additional templates from
  upstream SAP repos.
- **near-miss scenarios** — Codex's eval marks 13 cases as near-miss
  (88-89 score). Often a 5-minute label tweak in draw.io desktop pushes
  these above 90.
- **prompts the selector can't resolve** — when the prompt mentions
  multiple equally-relevant scenarios (e.g. "Joule with Federated ML
  via Cloud Connector"), the human picks the right template by browsing
  `template_browser/index.html` and forces it with `--template`.

## How to expand template coverage (one-time effort)

The single highest-leverage way to break the 22/63 plateau is to
**bundle more SAP templates that fill the ceiling-limited families**.

Two upstream sources, both Apache-2.0:

1. <https://github.com/SAP/sap-btp-reference-architectures> — 32
   editable .drawio files; many cover scenarios our 63 templates miss
   (specifically: industry-specific integrations, advanced data flows).
2. <https://github.com/SAP/architecture-center> — already curated; we
   have 52 of these. The remainder are mostly variants of bundled ones.

The mechanical step:

```bash
git clone --depth 1 https://github.com/SAP/sap-btp-reference-architectures.git \
  .cache/external/sap-btp-reference-architectures

# Score the external corpus to identify high-value additions
python3 scripts/eval_corpus.py inventory \
  --references .cache/external/sap-btp-reference-architectures
```

For each scenario where our loop is ceiling-limited, look in the
external corpus for a closer-match template, then copy it into
`assets/reference-examples/` and add metadata to
`assets/reference-examples/template-metadata.json`.

## What NOT to do

- **Don't run `eval_corpus.py run` overnight expecting more passes.**
  The plateau is real. Code/template changes are what move the needle,
  not LLM retries.
- **Don't try to write `.drawio` XML by hand or have an LLM emit it
  from scratch.** The XML is dense, draw.io has many subtle requirements
  (UserObject ids, layered mxGeometry, etc.), and hand-written diagrams
  consistently fall to ~50/100 fingerprint score.
- **Don't add features that the SAP reference doesn't have.** Adding a
  bottom legend block to a template that doesn't have one *lowers* the
  fingerprint score because it adds shapes/colors/cells the reference
  lacks.

## Realistic time budget per diagram

| Diagram complexity | Time | Source |
|---|---|---|
| Easy: same-family template available, minor relabel | 5-10 min | scaffold + 2-3 label edits + validate |
| Medium: same-family template, many service swaps | 15-25 min | scaffold + 5-10 label edits + icon swaps + validate + iterate |
| Hard: ceiling-limited family, structural rework | 30-45 min | scaffold + manual zone restructure in draw.io + iterate |
| Very hard: scenario not represented in corpus | 60+ min | bundle a new template first, then proceed |

Compare to authoring from scratch with the official SAP starter kit:
typically 60-120 minutes for a polished L2 diagram. The skill cuts that
roughly in half by removing the boilerplate and gating quality.
