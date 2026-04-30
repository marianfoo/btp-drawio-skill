# How this skill stays close to the SAP standard

A claim like "this plugin produces SAP-Architecture-Center-style diagrams" is only believable if there's an empirical way to measure it. This file documents the comparison harness, the fidelity numbers, and the workflow that produces high-fidelity output.

## The fingerprinting harness — `scripts/compare.py`

`compare.py` extracts a structural + style fingerprint from any `.drawio` file and computes a similarity score against another `.drawio` file. The fingerprint covers:

| Dimension | What's checked |
|-----------|----------------|
| **Canvas** | `pageWidth × pageHeight` — should match the selected SAP template; `1169 × 827` is the default for new L2 diagrams |
| **Counts** | total cells, vertices, edges, icons (cells with SAP-icon SVG data URI), pills (cells with `arcSize=50`) |
| **Palette** | the set of hex colors in the file (Jaccard similarity) |
| **Fonts** | `fontFamily` values used (subset = full credit) |
| **Stroke widths** | the set of `strokeWidth` values |
| **Polish** | presence of `absoluteArcSize=1`, `labelBackgroundColor=default`, grid-snap rate |
| **Labels** | visible label count and label-token overlap, so wrong-target templates no longer score as perfect |

The score is a weighted blend of these dimensions; 100 means the two files have an identical fingerprint, 0 means nothing in common.

```bash
python3 scripts/compare.py reference.drawio candidate.drawio
python3 scripts/compare.py --score reference.drawio candidate.drawio    # one-line score
python3 scripts/compare.py --json reference.drawio candidate.drawio     # machine-readable
```

Calibration:

| Pair | Expected score |
|------|----------------|
| File compared to itself | 100 |
| Different SAP-published L2 diagrams (e.g. IAS Authentication vs Task Center) | 80–85 |
| L0 of a scenario vs L2 of the same scenario | 60–70 |
| Hand-crafted candidate built from scratch | 50–55 |
| Candidate built by **copying a reference + relabeling** (the recommended workflow) | 95–100 when the target scenario stays close |

The big gap between "from-scratch" (≈50) and "from-template" (≈100) is the empirical justification for the SKILL.md rule: **never draw from scratch — always start from a reference template.**

## The full quality loop

```
description ┐
            │
            ▼
┌──────────────────────────────────────────────────────────┐
│ Step 1 — pick the closest reference template             │
│   select_reference.py ranks 63 bundled SAP templates     │
│   using metadata aliases/tags + visible draw.io labels   │
└──────────────────────────────────────────────────────────┘
            │
            ▼
┌──────────────────────────────────────────────────────────┐
│ Step 2 — copy + relabel for the new scenario             │
│   Title, zone labels, service-card values; preserve      │
│   geometry, edges, pills, legend                         │
└──────────────────────────────────────────────────────────┘
            │
            ▼
┌──────────────────────────────────────────────────────────┐
│ Step 3 — autofix.py --write                              │
│   Snap grid, normalise hex case, fix arcSize, strokeWidth│
└──────────────────────────────────────────────────────────┘
            │
            ▼
┌──────────────────────────────────────────────────────────┐
│ Step 4 — validate.py                                     │
│   Errors: bent arrows, label overflow, sibling overlap,  │
│   missing geometry, duplicate ids                        │
│   Warnings: off-palette, off-grid, missing label-bg      │
└──────────────────────────────────────────────────────────┘
            │
            ▼
┌──────────────────────────────────────────────────────────┐
│ Step 5 — score_corpus.py across all bundled references   │
│   Best score should be ≥ 90 if template drift is low     │
│   If < 90, compare.py shows where the structure drifted  │
└──────────────────────────────────────────────────────────┘
            │
            ▼
   final .drawio + flow narration
```

For `eval_corpus.py run --exclude-target-template`, the exact target is removed from the selector pool. The harness therefore adds an explicit primary visual-neighbor hint computed with `compare.py` fingerprints. This is not used for normal production generation; it makes the leave-one-out research loop test the closest available SAP layout instead of an arbitrary semantic neighbor.

## Worked example — `examples/iam-arc1-mcp-l2.drawio`

The bundled `examples/iam-arc1-mcp-l2.drawio` was produced by:

1. Picking `btp_SAP_Cloud_Identity_Services_Authentication_L2.drawio` as the closest reference template (it's the canonical IAM-on-BTP diagram).
2. Surgically swapping ~5 labels for an ARC-1 MCP scenario:
   - title: `Authentication with SAP Cloud Identity Services` → `ARC-1 MCP Server - Authentication on SAP BTP`
   - subtitle: `Recommended authentication flows…` → `Claude Desktop / Copilot Studio MCP clients calling ARC-1 over XSUAA OAuth, reaching on-prem SAP via Cloud Connector with Principal Propagation`
   - card label: `SuccessFactors` → `ARC-1 MCP Server`
   - zone label: `SAP BTP Applications -IAM based on SAP Cloud Identity Services` → `SAP BTP Applications - ARC-1 MCP based on SAP Cloud Identity Services`
   - card label: `Mobile/Desktop` → `Claude Desktop / Copilot Studio`
3. Running `autofix.py --write` (resulted in 436 mechanical fixes — geometry snap, hex case, arc size, font normalisation, comment strip).
4. Running `validate.py` — exit 0.
5. Running `compare.py` against the original reference — **scored 96.6/100** with the target-aware label-token scorer.
6. Running `score_corpus.py --min-score 90` across the 63 bundled templates — best score **96.6/100**.

This proves the workflow: with a few hand-edits, you preserve SAP's visual structure while the scorer still notices intentional scenario-label changes.

## Why the validator + autofix matter

Without these gates, a hand-crafted candidate scored **~52** even when it followed the rules in `references/`. The biggest contributors to the gap:

- Bent `orthogonalEdgeStyle` arrows (centers not aligned)
- Sparse zones with too few service cards (low vertex / icon count)
- Off-palette hex from improvising "close-enough" colors
- Missing `labelBackgroundColor=default` on edge labels

`validate.py` catches all of these before the diagram is shown to the user. `autofix.py` repairs the mechanical ones automatically.

## Limitations

The fingerprint compares **structure, style, and visible label overlap** — not full semantic correctness. Two diagrams with similar fingerprints can still encode different architectures. The score validates "looks SAP-styled and uses similar target labels" but doesn't validate "the architecture actually works".

Also, the validator can't check:

- **One-SAP-logo rule** — multiple logos count as warnings only when they appear inline in the XML
- **Semantic correctness of arrows** — green / pink / indigo edges are colored correctly, but whether *that specific edge* should be authentication, trust, or authorization is a judgment call left to the author
- **Legend completeness** — presence of a legend block is checked; whether it accurately covers all colors in the diagram is not

For those, manual review against `references/do-and-dont.md` remains necessary.

## Corpus scoring

`score_corpus.py` wraps `compare.py` and ranks the candidate against every bundled `.drawio` reference:

```bash
python3 scripts/score_corpus.py --top 5 --min-score 90 my-diagram.drawio
```

Use this as the final fidelity gate. A good template-derived diagram should have:

| Signal | Target |
|---|---|
| Best target/corpus score | `>= 90` |
| Chosen-template pairwise score | `>= 90`, ideally `95-100` |
| Validator errors | `0` |
| Off-palette / line-style drift | explainable or fixed |

For research runs against SAP's full public corpus, clone the upstream repositories and pass them as reference directories:

```bash
python3 scripts/score_corpus.py \
  --references /path/to/SAP/btp-solution-diagrams \
  --references /path/to/SAP/architecture-center \
  my-diagram.drawio
```

See `corpus-findings.md` for the 2026 snapshot that motivated the 63-template bundle.

## How to add new reference templates

1. Drop a `.drawio` file in `assets/reference-examples/` (any name)
2. Confirm it's Apache-2.0 / MIT / your own work
3. Add an entry to `assets/NOTICE.md` if the source is third-party
4. Re-score your test diagrams against the new template — `score_corpus.py --top 10`

The skill picks the highest-scoring reference automatically when the user describes a scenario, so adding more references improves quality monotonically.
