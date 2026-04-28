# SAP Reference Corpus Findings

Research snapshot: 2026-04-28.

Sources:

- `SAP/btp-solution-diagrams` at commit `c9860da`
- `SAP/architecture-center` at commit `e76ce36`
- SAP Community announcement: <https://community.sap.com/t5/technology-blogs-by-sap/announcement-new-release-of-content-and-central-entry-point-for-sap-btp/bc-p/14011436>

## Corpus Size

The current public corpus contains 138 editable `.drawio` diagrams:

| Source | `.drawio` files | Role |
|---|---:|---|
| `SAP/btp-solution-diagrams/assets/editable-diagram-examples` | 11 | canonical BTP Solution Diagram examples |
| `SAP/architecture-center/docs/ref-arch/**/drawio` | 127 | Architecture Center reference architecture diagrams |

The raw upstream draw.io corpus is about 24 MB. This plugin bundles a curated 63-template subset: all 11 canonical BTP examples plus 52 Architecture Center templates chosen for broad SAP BTP coverage.

## What the Live Corpus Shows

Common page sizes:

| Page size | Count | Use |
|---|---:|---|
| `1169 x 827` | 46 | canonical landscape canvas; safest default |
| `1100 x 850` | 22 | Architecture Center landscape variant |
| `1654 x 1169` | 17 | large A3-style landscape |
| `850 x 1100` | 15 | portrait variant |
| `827 x 1169` | 13 | canonical portrait variant |

Top observed colors outside embedded SVG icon payloads:

| Hex | Count | Meaning / note |
|---|---:|---|
| `#475E75` | 2167 | non-SAP area border / neutral stroke |
| `#1D2D3E` | 2139 | title / primary text |
| `#FFFFFF` | 1865 | card fill / background |
| `#0070F2` | 1627 | SAP / BTP area border |
| `#188918` | 782 | positive / authentication flow |
| `#F5F6F7` | 576 | non-SAP area fill |
| `#EBF8FF` | 525 | SAP / BTP area fill |
| `#00185A` | 503 | dark SAP blue variant used in Architecture Center diagrams |
| `#5D36FF` | 467 | indigo / authorization flow |
| `#266F3A` | 402 | dark positive green variant |
| `#CC00DC` | 323 | pink / trust flow |

Observed font families:

| Font | Count | Guidance |
|---|---:|---|
| `Helvetica` | 3494 | default for generated diagrams |
| `Arial` | 1978 | appears in SAP files, often inside rich text labels |
| `72 Brand` | 124 | appears in some newer Architecture Center files; do not introduce unless inherited from a template |

Observed stroke widths:

| Stroke width | Count | Guidance |
|---|---:|---|
| `1.5` | 5902 | dominant border / connector weight |
| `2` | 627 | secondary connector / emphasis |
| `1` | 456 | pills, small cards, light dividers |
| `3` | 86 | heavy emphasis |
| `4` | 10 | firewall / very heavy boundary |

## Implementation Decisions

- Keep `1169 x 827` as the default canvas because it is both the canonical BTP examples' size and the most common live corpus size.
- Keep `Helvetica` as the generated-diagram default. `Arial` and `72 Brand` are accepted as inherited upstream-template variants but should not be newly introduced by the skill.
- Expand the validator palette with observed SAP variants such as `#00185A`, `#0057D2`, `#2395FF`, `#D1EFFF`, and common neutral variants so the validator does not fight real Architecture Center files.
- Validate duplicate IDs per draw.io page, not globally across the entire `.mxfile`; multi-page upstream files can reuse `0` / `1` root IDs safely.
- Bundle representative templates rather than every raw upstream diagram. The full corpus can still be used for research by cloning the SAP repos and passing them to `score_corpus.py --references`.

## Operational Loop

For a generated candidate:

1. Run `select_reference.py` on the user's request and pick from the top 3 candidates.
2. Copy the selected template and preserve geometry, canvas, container rhythm, legend style, and line/pill density.
3. Relabel and replace only the content required by the user's scenario.
4. Run `autofix.py --write`.
5. Run `validate.py`.
6. Run `score_corpus.py --min-score 90`.
7. If the score is below 90, use `compare.py` against the selected template and restore the dimensions that drifted.

The point of the loop is not to make every generated diagram identical. It is to keep the structural fingerprint close enough that a new diagram reads as part of the SAP Architecture Center system rather than as a generic draw.io sketch.
