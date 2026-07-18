# Identity Pack Workflow

Use this route when the identity story needs separate landscape, authentication/trust, and provisioning views. The default pattern composes three pinned pages from SAP Architecture Center RA0019 templates:

1. `00--Identity-Landscape` — capability and claim-state context.
2. `01--IAS-Proxy-and-BTP-Trust` — IAS broker pattern and SAP BTP trust boundary.
3. `02--IPS-Provisioning` — Identity Provisioning lifecycle route.

The pages describe an evidence-bounded pattern. They do not prove configured tenants, protocol choices, transformations, schedules, mappings, or operating results.

## Build and validate

Run the offline freshness check on every build. Add `--live` when network access is available or before consequential external use; a changed release tag or stale dated claim is blocking until reviewed.

```bash
python3 "$SKILL_DIR/scripts/check_currentness.py"
python3 "$SKILL_DIR/scripts/scaffold_identity_pack.py" --out identity-pack.drawio
python3 "$SKILL_DIR/scripts/validate_semantics.py" identity-pack.drawio identity-pack.spec.json
python3 "$SKILL_DIR/scripts/provenance.py" identity-pack.drawio --audit --strict
```

The pattern file is `assets/patterns/identity-architecture-pack.json`. Every page retains its own template, SHA-256 pin, and direct upstream source. The schema-v2 semantic specification distinguishes SAP product capability, proposed design, configured client state, client confirmation, and narrowly scoped protocol exceptions.

## Controlled variation

For exact label changes, pass a UTF-8 CSV to `scaffold_identity_pack.py --variation-csv`. Required columns are `page`, `match`, `replacement`, and `claim_state`. Add the evidence field required by the state: for example `decision_status` for a proposal or `evidence` for configured client state. Every match must resolve exactly once on its named page.

For a topology that does not yet fit a template, use `build_csv_variation.py` with columns `id,label,connect_to,protocol,claim_state` plus state-specific evidence columns. Its draw.io CSV is an auto-layout draft, not a deliverable.

For an authentication or provisioning interaction, use `build_sequence_draft.py` with structured JSON participants and messages. Each message is claim-controlled. The Mermaid output is likewise a draft to review and integrate into a template-derived page.

Never treat CSV or Mermaid import as permission to bypass SAP styling, provenance, semantic validation, or visual review.

## Export and review

```bash
python3 "$SKILL_DIR/scripts/export_pack.py" identity-pack.drawio \
  --spec identity-pack.spec.json \
  --targets identity-pack.targets.json \
  --out-dir identity-pack-exports \
  --emit-page-drawio
```

SVG, PNG, and PDF are clean exports by default. Use `--embed-diagram` only when a consumer explicitly needs editable XML inside the derivative. `export-manifest.csv` and `export-manifest.json` bind every file to the canonical `.drawio` hash.

Run `verify_delivery.py` against each emitted page with its emitted schema-v1 spec and its pinned `source_template`. Inspect candidate and reference renders, record the hash-bound visual review, and rerun the gate. The pack passes only when all pages pass.

## Currentness boundaries

`assets/currentness.json` tracks SAP BTP solution-diagram releases, SAP Architecture Center releases, and dated identity claims. Keep deprecation wording scenario-specific:

- SAP KBA 3521979 concerns the recorded SAP BTP Cloud Foundry user-interactive trust scope; it is not a universal IAS or SAP SaaS SAML retirement statement.
- The recorded 30 November 2026 deadline concerns the documented SAP Cloud Identity Access Governance user-group synchronization scenario; it is not a universal SCIM v1 deadline.
