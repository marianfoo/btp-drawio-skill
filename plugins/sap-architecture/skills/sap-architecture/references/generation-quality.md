# Diagram generation quality checklist

This checklist distills the research used to improve generated SAP BTP diagrams.

## General architecture diagram quality

- A diagram should stand alone: title, scope, notation, and acronyms must be understandable without a long narration.
  Source: https://c4model.com/diagrams/notation
- Avoid ambiguous boxes and lines: element purpose, technology/protocol, and relationship intent should be visible.
  Source: https://c4model.com/introduction
- Every meaningful relationship should be directional and labelled with a specific intent or protocol where possible.
  Source: https://c4model.com/diagrams/notation
- Keep abstraction level consistent; mixing overview and implementation details makes diagrams hard to read.
  Source: https://c4model.com/introduction

## SAP-specific quality

- Use the SAP BTP starter kit, official templates, and shape libraries instead of starting from blank XML.
  Source: https://architecture.learning.sap.com/docs/community/diagrams
- Keep icon sizes, text formatting, and line styles consistent; do not invent custom arrows.
  Source: https://architecture.learning.sap.com/docs/community/diagrams
- Use the BTP service icon version with the grey background circle.
  Source: https://sap.github.io/btp-solution-diagrams/docs/btp_guideline/diagr_comp/icons/
- Preserve SAP area colors and 16 px corner radius; use accent colors sparingly.
  Source: https://sap.github.io/btp-solution-diagrams/docs/btp_guideline/diagr_comp/areas/
- Use connector semantics consistently: trust is usually pink, authentication green, authorization indigo, and firewalls/network barriers thick grey.
  Source: https://sap.github.io/btp-solution-diagrams/docs/btp_guideline/diagr_comp/lines_connectors/
- Do not downscale whole diagrams to fit; SAP's text sizes and line styles are tuned for the target medium.
  Source: https://sap.github.io/btp-solution-diagrams/docs/solution_diagr_intro/big_picture/

## Implementation consequences

- `select_reference.py` prefers explicit reference families such as `RA0001`, preserves explicit L0/L1/L2 level hints, and reads curated `template-metadata.json` aliases/tags so generic labels like `Page-1` do not dominate selection.
- Generic Agentic AI + Joule prompts should anchor on `ac_RA0029_AgenticAI_root.drawio`; use the Embodied AI template only for explicit embodied/robotic/physical-agent scenarios.
- `eval_corpus.py create` provides a direct description-to-diagram path for smoke tests and examples.
- Preserve SAP Architecture Center reference-canvas structure, including white background, SAP footer/reference id/QR where present, network dividers, and inline pill notation. Do not add a dark dashboard background or a bottom legend band to templates that do not already have one.
- `eval_corpus.py run --exclude-target-template` now reports the nearest visual fallback templates computed from SAP fingerprints. These hints keep leave-one-out evaluation focused on visual fidelity when the exact target template is intentionally unavailable. Use `--no-style-neighbor-hints` for a pure semantic selector test.
- Overnight runs classify failures into `near-miss` and `ceiling-limited`. A ceiling-limited case means the chosen alternate SAP template is structurally too far from the target; add a closer sibling template or improve geometry-aware generation instead of spending more model attempts.
- Use the default `--retry-margin 8` for long local runs. With `--min-score 90`, it retries only cases that already score 82+ and stops early on low-ceiling cases.
- Use `references/external-test-corpus.md` for the second-stage external SAP run. The older `SAP/sap-btp-reference-architectures` diagrams are useful stress cases because they cover legacy and methodology-driven layouts that are not all visually close to the bundled templates.
- The Ollama prompt now asks for protocols/flow semantics, target-audience consistency, and conservative template label replacements.
- Model label edits do not rewrite reserved legend/notation labels such as `Access`, `Authentication`, `Authorization`, `Trust`, or `Deployment`.
- Unguarded model replacements are limited to title/service labels or near-typo corrections, reducing semantic drift.
- Scoring normalizes known SAP upstream typos such as `Adminstrator`, `Provisoning`, and `Plaforms`, so corrected output is not penalized.
- Per-attempt `target-compare.json` and `best-corpus-compare.json` files explain why a candidate did or did not match the target.
- Ollama runs use `/api/generate` with a JSON schema by default, temperature `0`, and CLI fallback if the local API is unavailable. This follows Ollama's structured-output guidance and keeps long runs machine-consumable.
- Retry attempts now receive compact score feedback from the previous attempt: validator counts, weak fingerprint dimensions, target diffs, and rejected label replacements. This makes second/third attempts useful for near-miss cases while leaving low-ceiling template gaps for human/template review.
- See `references/improvement-options.md` for the researched option ranking and why direct XML generation, generic autolayout, and fine-tuning are not the best next moves for SAP-style fidelity.
