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

- `select_reference.py` prefers explicit reference families such as `RA0001` and preserves explicit L0/L1/L2 level hints.
- `eval_corpus.py create` provides a direct description-to-diagram path for smoke tests and examples.
- The Ollama prompt now asks for protocols/flow semantics, target-audience consistency, and conservative template label replacements.
- Model label edits do not rewrite reserved legend/notation labels such as `Access`, `Authentication`, `Authorization`, `Trust`, or `Deployment`.
- Unguarded model replacements are limited to title/service labels or near-typo corrections, reducing semantic drift.
- Scoring normalizes known SAP upstream typos such as `Adminstrator`, `Provisoning`, and `Plaforms`, so corrected output is not penalized.
- Per-attempt `target-compare.json` and `best-corpus-compare.json` files explain why a candidate did or did not match the target.
