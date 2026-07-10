# Guarded Workflow

## Gate Model

The workflow uses four independent proofs:

| Proof | Question | Evidence |
|---|---|---|
| Semantic | Does the diagram contain the agreed architecture? | `<name>.spec.json` plus `validate_semantics.py` |
| Provenance | Is the modified template clearly a derivative without stale official identifiers? | `provenance.py --audit --strict` |
| Structural/style | Is it technically valid and close to the selected SAP template? | strict warning delta plus pinned-template score |
| Visual | Did a reviewer inspect the actual rendered pixels? | hash-bound `visual-review.json` |

No proof substitutes for another. Corpus similarity is not semantic correctness; XML validation is not visual review; a visual review is not SAP source evidence.

## Working Files

Keep these together during a run:

```text
<name>.drawio
<name>.spec.json
.cache/sap-architecture-review/<name>/
  candidate.png
  reference.png
  gate-report.json
  visual-review.json
```

The `.drawio` file is the editable artifact. The specification and gate report are the audit trail. Cache outputs can remain uncommitted unless the project needs durable evidence.

## Structural Strictness

SAP source templates sometimes contain warnings under the local validator. The final gate compares candidate warnings with the exact pinned source template:

- inherited warning with the same cell and message: tolerated and reported;
- new warning introduced by editing: blocking;
- any candidate validator error: blocking;
- template validator error: reported as an upstream-fixture warning and must be considered during visual review.

This avoids silently normalizing SAP-authored geometry while preventing new defects.

## Pinned Target

Always preserve the exact template selected by `scaffold_diagram.py`. In template mode, the final score is against that file, not the highest-scoring file in the whole corpus. A best-corpus score can be high for the wrong architecture family and is therefore diagnostic only.

If the target changes, record the new selection and rerun provenance, validation, rendering, and visual review.

When visual inspection shows that even the closest template preserves an unrelated architecture family, reject that candidate and use the documented semantic fallback. Keep the closest template as the rendered style reference, require zero candidate warnings and SAP-likeness at least 90, and treat pinned-template similarity as diagnostic. Do not use fallback merely to escape a failing template score.

## Provenance Rules

- Mark the mxfile as a guarded derivative.
- Store the source template name and direct upstream URL.
- Add a visible statement that the modified artifact is not an official SAP Reference Architecture.
- Remove source-specific RA ids, Architecture Center links, and identified QR/reference cells.
- Treat unresolved square embedded raster images as blocking until reviewed.
- Preserve SAP starter-kit styling and licensed assets according to `assets/NOTICE.md`; do not imply SAP endorsement of the modified architecture.

## Visual Review

Inspect the candidate at useful zoom and compare it with the pinned source. Confirm:

1. The candidate and reference renders are nonblank and correctly framed.
2. Labels are readable and not clipped.
3. Cards, pills, icons, and lines do not overlap incoherently.
4. Every required flow can be traced in the requested direction.
5. The derivative attribution is visible and source-specific QR/reference media is absent.
6. SAP visual language remains coherent without preserving irrelevant source branches.

Record specific observations. `Looks good` is not an adequate review note.

## Status Language

- `internal-draft`: artifact gates may pass, but architecture assumptions or source evidence remain open.
- `external-safe-generic`: generic architecture, sanitized provenance, and all artifact gates pass; no client-specific claim is implied.
- `client-specific-final-candidate`: client/project sources support the content, SAP deliverable gates and Marc review have run, and all artifact gates pass. Human client-context review still remains.

Never use `client-ready` or `official SAP reference architecture` for a generated derivative.
