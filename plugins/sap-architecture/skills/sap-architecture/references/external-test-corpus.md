# External SAP diagram test corpus

The bundled 63 templates remain the default because they are curated, compact, and versioned with this plugin. For deeper quality work, use external SAP repositories as opt-in test corpora under `.cache/`.

## Recommended external corpus

### `SAP/sap-btp-reference-architectures`

- Source: https://github.com/SAP/sap-btp-reference-architectures
- License: Apache-2.0.
- Why it matters: this repository contains 32 editable `.drawio` SAP BTP reference architecture files across Work Zone, Build Process Automation, Task Center, Private Link, multi-region resiliency, Datasphere, OpenAI/RAG, Federated ML, IAM, API-managed integration, B2B, B2G, A2A, and Master Data Integration.
- Local finding from 2026-05-01: 27 of 32 files score below 90 against the bundled corpus, and 18 score below 80. That makes it a useful stress suite for template coverage and geometry drift, not just a duplicate corpus.
- Baseline leave-one-out run from 2026-05-01: 7 passed, 7 near-miss, 18 ceiling-limited. Run this after the bundled suite to find template gaps that the main corpus does not expose.

Clone it under `.cache/`:

```bash
mkdir -p .cache/external
git clone --depth 1 https://github.com/SAP/sap-btp-reference-architectures.git \
  .cache/external/sap-btp-reference-architectures
```

Run a dry-run first:

```bash
python3 plugins/sap-architecture/skills/sap-architecture/scripts/eval_corpus.py dry-run \
  --references .cache/external/sap-btp-reference-architectures \
  --limit 8 \
  --generator ollama \
  --model qwen3.6:35b-a3b-nvfp4 \
  --exclude-target-template \
  --apply-model-plan \
  --max-attempts 3 \
  --retry-margin 8 \
  --min-score 90
```

Run the external overnight suite after the bundled suite:

```bash
caffeinate -dimsu -- \
python3 plugins/sap-architecture/skills/sap-architecture/scripts/eval_corpus.py run \
  --references .cache/external/sap-btp-reference-architectures \
  --generator ollama \
  --model qwen3.6:35b-a3b-nvfp4 \
  --exclude-target-template \
  --apply-model-plan \
  --max-attempts 3 \
  --retry-margin 8 \
  --min-score 90 \
  --timeout-seconds 1200 \
  --continue-on-error \
  2>&1 | tee .cache/sap-architecture-eval/external-sap-btp-reference-architectures.log
```

## Sources not recommended for committed test fixtures

### SAP Discovery Center

SAP Discovery Center has useful BTP reference architecture descriptions and downloadable diagrams, but its terms are narrower than Apache-2.0. Treat it as a source of scenario ideas or private/internal tests only unless the specific artifact has a compatible license.

### Lucidchart marketplace and draw.io built-in SAP shapes

These are useful for asset coverage checks and visual expectations, but they are not a convenient `.drawio` target corpus. Use them to verify that official BTP service icons, area shapes, number markers, and connector conventions remain represented in `assets/asset-index.json`.

### `SAP-samples/teched2023-XP286v`

This is useful historical training material for the BTP solution diagram workflow, but it does not currently provide extra `.drawio` target files. Do not use it as a scoring corpus.

## How to interpret external results

- High corpus score and low target score means the generated diagram is still SAP-styled but the selected bundled template is structurally unlike the external target.
- `ceiling-limited` external cases are candidates for adding new templates or geometry-aware generation.
- `near-miss` external cases are candidates for selector metadata, label replacement, or a small number of additional model attempts.
- Do not commit generated `.cache/` outputs. Promote only reviewed examples or new legally compatible references.
