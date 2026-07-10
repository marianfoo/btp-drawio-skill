---
name: sap-architecture
description: Create, edit, or review editable SAP Architecture Center-style draw.io diagrams for SAP BTP, Cloud Foundry, Kyma, ABAP environment, Cloud Connector, SAP S/4HANA, Fiori, SAP Build, Joule, IAM/XSUAA, integration, resiliency, data, and AI-agent landscapes. Use when the requested artifact is an SAP architecture, topology, trust, authentication, authorization, deployment, or solution-flow diagram in `.drawio` format. Produces a template-derived diagram with a pre-authored semantic specification, safe derivative attribution, strict structural-delta validation, pinned-template scoring, rendered visual review, and a machine-readable completion report. Do not use for generic non-SAP flowcharts, or to approve unsupported SAP architecture claims.
---

# SAP Architecture Diagram

Produce an editable SAP-style `.drawio` diagram without confusing visual fidelity with architecture correctness.

## Boundaries

- For SAP security, client deliverables, KDDs, proposals, or evidence-bearing architecture claims, run `sap-deliverable-start` first. Use this skill only after the content is approved or explicitly staged as an assumption.
- This skill authors and verifies the diagram artifact. It does not replace source review, SAP evidence gates, the SAP risk boundary, or Gerard's Marc review gate.
- Start from a bundled SAP template. Use `render_semantic.py` only when the template selector cannot represent the requested architecture family.
- Remove or replace source-specific QR codes, reference identifiers, and official links. A modified diagram must say that it is derived and not an official SAP Reference Architecture.
- Never claim `ready`, `pixel-polished`, or visually verified without a passing `gate-report.json` bound to a passing visual-review record.

## Resolve The Skill

Set `SKILL_DIR` to the absolute directory containing this `SKILL.md`. Run every bundled script through that path:

```bash
python3 "$SKILL_DIR/scripts/<script>.py" ...
```

Do not assume `.claude/skills`, `.codex/skills`, the repository root, or the caller's current directory.

## Required Workflow

### 1. Lock semantics before selecting a template

Create `<name>.spec.json` from the request before scaffolding. Record:

- audience level (`L0`, `L1`, or `L2`);
- required zones and nodes, including aliases;
- directed required flows;
- required protocol/trust terms;
- forbidden or explicitly excluded terms;
- allowed raster-image hashes only after visual inspection.

Read `references/semantic-spec.md` for the exact schema. If the request is too vague to name the main app/flow, services, backends, and protocol, ask one concise question. Do not manufacture unsupported components to complete the specification.

### 2. Scaffold and pin the target

Use the scoped architecture description, not an unfiltered long source document:

```bash
python3 "$SKILL_DIR/scripts/scaffold_diagram.py" \
  "<scoped architecture request>" \
  --include-external-sap-references \
  --out <name>.drawio
```

Record the exact selected template path as `TARGET`. If the selector is ambiguous, inspect the printed alternatives or use `template_browser.py`; choose the simpler template at the correct level.

### 3. Mark the derivative immediately

Run provenance sanitization before editing:

```bash
python3 "$SKILL_DIR/scripts/provenance.py" <name>.drawio \
  --source-template "$(basename "$TARGET")" \
  --source-url "<direct upstream source URL>" \
  --write
```

This strips detectable official reference identifiers/links and adds visible derivative attribution. Audit any square embedded raster flagged as a possible QR/reference image. Allow its hash in the semantic specification only after inspecting the rendered image and confirming what it is.

### 4. Make the smallest architecture change

- Prefer `relabel.py` for text changes.
- Use `extract_icon.py` and `extract_asset.py` for official assets.
- Duplicate proven template cells for additions; preserve grid, hierarchy, icon scale, and connector semantics.
- Preserve imported template invariants: do not assume root/layer IDs `0`/`1`, positive coordinates, or grid snapping. If the source has `grid="0"`, keep off-grid geometry unless a visible defect requires a deliberate edit.
- When a required conceptual flow terminates on a pill, group, or visually routed edge that should not be rebound, add semantic-only `data-semantic-source` and `data-semantic-target` attributes to the edge. Preserve the visible `source`, `target`, and route geometry.
- Remove irrelevant branches completely, including their edges, pills, and number markers.
- Keep the semantic specification synchronized when Gerard changes the requested architecture. Never weaken the specification merely to make a bad diagram pass.

Read `references/manual-workflow.md` for editing and `references/do-and-dont.md` for SAP visual rules. Read `references/nudge-workflow.md` when more than relabeling is needed.

### 5. Repair and run deterministic gates

```bash
python3 "$SKILL_DIR/scripts/autofix.py" --write <name>.drawio
python3 "$SKILL_DIR/scripts/validate_semantics.py" <name>.drawio <name>.spec.json
python3 "$SKILL_DIR/scripts/provenance.py" <name>.drawio --audit --strict
```

Then run the guarded final gate. In template mode it compares warnings against the pinned pristine target, so inherited SAP-template warnings are tolerated but new warnings fail:

```bash
python3 "$SKILL_DIR/scripts/verify_delivery.py" \
  <name>.drawio <name>.spec.json \
  --target "$TARGET" \
  --out-dir .cache/sap-architecture-review/<name>
```

The first run must stop at `awaiting-visual-review` and produce `candidate.png`, `reference.png`, and `gate-report.json`. Any other failure must be fixed before review.

For a justified `render_semantic.py` fallback, keep the nearest SAP template as the visual reference and add `--mode semantic-fallback`. In that mode every structural warning is new and blocking, SAP-likeness must be at least 90, and pinned-template similarity is diagnostic rather than the pass threshold.

### 6. Inspect and bind the visual review

Open both PNGs with the available image-viewing tool. Check that they are nonblank, legible, free of incoherent overlap, traceable flow-by-flow, visibly marked as a derivative, and consistent with the selected SAP template's visual language.

After actually inspecting both images, record the review:

```bash
python3 "$SKILL_DIR/scripts/record_visual_review.py" \
  .cache/sap-architecture-review/<name>/candidate.png \
  .cache/sap-architecture-review/<name>/reference.png \
  --out .cache/sap-architecture-review/<name>/visual-review.json \
  --reviewer "<reviewer>" --verdict pass \
  --notes "<specific observations>" \
  --check nonblank --check legible --check no_incoherent_overlap \
  --check flows_traceable --check provenance_visible --check sap_style_consistent
```

Re-run `verify_delivery.py` with:

```bash
--visual-review .cache/sap-architecture-review/<name>/visual-review.json
```

The final status must be `pass`. The review is hash-bound; any rerendered or changed image invalidates it.

### 7. Hand off the artifact

Report:

- diagram and semantic-spec paths;
- pinned source template and source URL;
- gate report and visual-review paths;
- semantic assumptions or unresolved external evidence;
- validation status using one of: `internal-draft`, `external-safe-generic`, or `client-specific-final-candidate`.

Print a numbered flow narration for the host document. Keep narration outside the canvas.

## Stop Conditions

Stop and report the exact gate when:

- required architecture content lacks an evidence route for external/client use;
- no template or semantic fallback supports the requested architecture family;
- semantic validation finds a missing node, term, or directed flow;
- provenance audit finds an unresolved source identifier or unreviewed QR-like raster;
- the candidate introduces structural warnings beyond the pinned template;
- pinned-template score is below 90 in template mode, or SAP-likeness is below 90 in semantic-fallback mode;
- draw.io rendering is unavailable;
- the rendered image has not been inspected or the hash-bound review is stale.

Never bypass a stop by lowering the score, deleting a semantic requirement, allowing an image hash without inspection, or recording a visual review that did not occur.

## Reference Routing

- Semantic contract and provenance: `references/semantic-spec.md`, `references/guarded-workflow.md`
- Level selection: `references/levels.md`
- Layout and styling: `references/layout.md`, `references/palette-and-typography.md`, `references/shapes-and-edges.md`
- SAP rules: `references/do-and-dont.md`, `references/generation-quality.md`
- Editing loop: `references/manual-workflow.md`, `references/nudge-workflow.md`
- Scoring methodology and corpus: `references/methodology.md`, `references/corpus-findings.md`
