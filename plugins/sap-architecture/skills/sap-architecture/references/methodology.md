# How this skill stays close to the SAP standard

A claim like "this plugin produces SAP-Architecture-Center-style diagrams" is only believable if there's an empirical way to measure it. This file documents the comparison harness, the fidelity numbers, and the workflow that produces high-fidelity output.

## The fingerprinting harness — `scripts/compare.py`

`compare.py` extracts a structural + style fingerprint from any `.drawio` file and computes a similarity score against another `.drawio` file. The fingerprint covers:

| Dimension | What's checked |
|-----------|----------------|
| **Canvas** | `pageWidth × pageHeight` — should always be `1169 × 827` |
| **Counts** | total cells, vertices, edges, icons (cells with SAP-icon SVG data URI), pills (cells with `arcSize=50`) |
| **Palette** | the set of hex colors in the file (Jaccard similarity) |
| **Fonts** | `fontFamily` values used (subset = full credit) |
| **Stroke widths** | the set of `strokeWidth` values |
| **Polish** | presence of `absoluteArcSize=1`, `labelBackgroundColor=default`, grid-snap rate |

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
| Candidate built by **copying a reference + relabeling** (the recommended workflow) | 95–100 |

The big gap between "from-scratch" (≈50) and "from-template" (≈100) is the empirical justification for the SKILL.md rule: **never draw from scratch — always start from a reference template.**

## The full quality loop

```
description ┐
            │
            ▼
┌──────────────────────────────────────────────────────────┐
│ Step 1 — pick the closest reference template             │
│   Selection guide in SKILL.md (27 templates available)   │
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
│ Step 5 — compare.py vs the reference                     │
│   Score should be ≥ 90 if you started from a template    │
│   If < 90, autofix may have over-corrected               │
└──────────────────────────────────────────────────────────┘
            │
            ▼
   final .drawio + flow narration
```

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
4. Running `validate.py` — clean.
5. Running `compare.py` against the original reference — **scored 100/100**.

This proves the workflow: with a few hand-edits, you get a fingerprint indistinguishable from SAP's canonical example.

## Why the validator + autofix matter

Without these gates, a hand-crafted candidate scored **~52** even when it followed the rules in `references/`. The biggest contributors to the gap:

- Bent `orthogonalEdgeStyle` arrows (centers not aligned)
- Sparse zones with too few service cards (low vertex / icon count)
- Off-palette hex from improvising "close-enough" colors
- Missing `labelBackgroundColor=default` on edge labels

`validate.py` catches all of these before the diagram is shown to the user. `autofix.py` repairs the mechanical ones automatically.

## Limitations

The fingerprint compares **structure and style** — not semantic correctness. Two diagrams with identical fingerprints can illustrate completely different scenarios. The score validates "looks SAP-styled" but doesn't validate "the architecture actually works".

Also, the validator can't check:

- **One-SAP-logo rule** — multiple logos count as warnings only when they appear inline in the XML
- **Semantic correctness of arrows** — green / pink / indigo edges are colored correctly, but whether *that specific edge* should be authentication, trust, or authorization is a judgment call left to the author
- **Legend completeness** — presence of a legend block is checked; whether it accurately covers all colors in the diagram is not

For those, manual review against `references/do-and-dont.md` remains necessary.

## How to add new reference templates

1. Drop a `.drawio` file in `assets/reference-examples/` (any name)
2. Confirm it's Apache-2.0 / MIT / your own work
3. Add an entry to `assets/NOTICE.md` if the source is third-party
4. Re-score your test diagrams against the new template — `compare.py --score`

The skill picks the highest-scoring reference automatically when the user describes a scenario, so adding more references improves quality monotonically.
