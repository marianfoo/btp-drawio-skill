# Nudge workflow — iterative LLM ↔ scripts loop

Audience: Cursor's Agent (Claude Sonnet / GPT) or Claude Code working on a single diagram with a human in the loop.

The goal of this workflow is **not** to one-shot a perfect diagram. It is to converge on one through small, reviewable edits — guided by the candidate PNG, the SAP target PNG, and a scored breakdown that names what to fix next.

## The 3-tool loop

```
            ┌───────────────────┐
            │ user nudge or     │
            │ initial prompt    │
            └─────────┬─────────┘
                      │
                      ▼
        ┌───────────────────────────┐
        │ LLM picks ONE small edit  │
        │ via the Edit / Write tool │
        └─────────────┬─────────────┘
                      │
                      ▼
        ┌───────────────────────────┐
        │ scripts/autofix.py --write│   ← mechanical clean-up
        └─────────────┬─────────────┘
                      │
                      ▼
        ┌───────────────────────────┐
        │ scripts/iterate.py        │   ← renders PNG, scores,
        │   <candidate>             │     prints next-step list
        │   [--target <ref>]        │
        └─────────────┬─────────────┘
                      │
                      ▼
        ┌───────────────────────────┐
        │ LLM reads:                │
        │   candidate.png           │   ← uses its vision tool
        │   reference.png           │
        │   suggestions list        │
        └─────────────┬─────────────┘
                      │
       score ≥ 90 ────┼──── score < 90
            │         │           │
            ▼         │           ▼
       PASS — done    │     pick next ONE edit
                      │     (loop)
                      ▼
              await user nudge
              ("move Joule to the left",
               "add MCP Gateway in BTP",
               "use teal pills for MCP")
```

## Key rules for the LLM

1. **One edit per iteration.** Resist the urge to fix five things at once. The score breakdown ranks dimensions by weighted impact — pick the top suggestion. Always re-run `iterate.py` after each edit so you can see the score delta.

2. **Always look at the PNGs.** The text breakdown will tell you "icons missing", but the PNG tells you *where* to put them. After every `iterate.py` run, open both `candidate.png` and `reference.png` with your vision/read tool. Reason about them visually, not only by hex value.

3. **Watch the delta.** `iterate.py` reports `↑+3.2` or `↓-1.5` since the previous run. If you went down, your last edit was wrong — undo it (your text editor's history or `git diff`) before trying something else. Don't pile bad edits on top of bad edits.

4. **Stop at PASS.** Once the score is ≥ 90 and the user has given no further nudge, stop. Don't keep editing in pursuit of 100 — you'll start replacing intentional differences (the candidate's scenario labels) with template defaults.

5. **When the user nudges in natural language**, treat it as a single edit step. "Make Joule purple" → find the Joule zone cell → change `fillColor` and `strokeColor` to `#F1ECFF` / `#5D36FF` → autofix → iterate. Don't conflate the nudge with other improvements you also see.

6. **Ask the user before destructive moves.** Examples that need confirmation: deleting a zone the user explicitly added, swapping the chosen template for a different one, regenerating the file from scratch. A nudge is small; if your only path to compliance is a rewrite, ask first.

## What `iterate.py` gives you

Every run prints a structured block. Read it carefully — every line is there to direct your next move:

```
─── SAP DIAGRAM ITERATION ───
candidate    : docs/architecture/foo.drawio
target       : ac_RA0029_AgenticAI_root.drawio  (corpus fingerprint match)
score        : 78.4 / 100   ↑+3.2 since last iteration
pass gate    : 90.0   (BELOW — keep iterating)

📷 Read these images with your vision tool to plan the next edit:
   candidate :  .cache/sap-architecture-iter/foo/foo.candidate.png
   reference :  .cache/sap-architecture-iter/foo/ac_RA0029_AgenticAI_root.reference.png
   side-by-side HTML : .cache/sap-architecture-iter/foo/review.html

⚠ Lowest-scoring dimensions (fix worst first):
   zones        45.0%  ████░░░░░░
   zone_depth   50.0%  █████░░░░░
   icons        55.0%  █████░░░░░
   pill_vocab   60.0%  ██████░░░░
   ...

✏ Next concrete edit (do ONE, then re-run iterate.py):
   1. Add 4 zone container(s). Reference has 8 zones; you have 4. Use rounded
      rect with arcSize=16, strokeWidth=1.5, and a top-left bold inline label.
   2. Add 6 BTP service icon(s). Use scripts/extract_icon.py
      "<service-name>" --x <X> --y <Y> --id <id> to get a ready mxCell.
   3. Replace 2 novelty pill verb(s). Allowed: TRUST, Authenticate, ...
   ...

✓ Score improved +3.2. Keep going.
```

## Translating nudges into edits

| User nudge | What you should do |
|---|---|
| "Make Joule purple" | Find the Joule zone cell (`<mxCell value="Joule"...>` or similar). Set `fillColor=#F1ECFF;strokeColor=#5D36FF`. autofix → iterate. |
| "Add MCP Gateway in BTP" | Look at the reference PNG to see where MCP Gateway goes. Duplicate an existing card (e.g. Custom Agents), change its label to `MCP Gateway`, use `extract_icon.py "Integration Suite"` for the icon, and put it inside the BTP zone parent. autofix → iterate. |
| "Move System Trigger to bottom-left" | Find the System Trigger cell, edit its `<mxGeometry x="..." y="...">` so x is small and y is high. Keep on 10-px grid. autofix → iterate. |
| "Use teal pills for the MCP flow" | Find the MCP-flow pill cells (likely `arcSize=50` near the cards you want connected). Set `fillColor=#DAFDF5;strokeColor=#07838F` on each. autofix → iterate. |
| "It looks too crowded" | Compare zone counts vs reference. If you have more zones than ref, remove the least-essential one. If geometry density is too high, increase canvas pageWidth/pageHeight (rare). autofix → iterate. |
| "I don't like this template, try a different one" | This is the destructive case — ask the user to confirm. If yes: `scaffold_diagram.py --template <other>.drawio --out <same-destination> --force`. The file will be replaced. |

## Common loops

### Initial-creation loop (after fresh scaffold)

1. Run `scaffold_diagram.py "<request>" --out foo.drawio` — produces a SAP-anchored starting point at ~100% structural similarity to its source template.
2. Run `iterate.py foo.drawio` — first iteration; it picks the source template as target automatically and reports near-100 score because edits haven't started.
3. Make label edits to fit the user's scenario (rename `SuccessFactors` → `ARC-1`, etc.).
4. After every 1-3 small edits, run `autofix.py --write foo.drawio && iterate.py foo.drawio`.
5. Loop until either the user is satisfied or score is ≥ 90.

### User-nudge loop (later refinement)

1. User says: "Joule should be on the left, not in the middle."
2. Read `candidate.png` from the last iterate run to see current Joule placement.
3. Read `reference.png` to understand the canonical SAP layout.
4. Make ONE edit: change Joule zone's `<mxGeometry x="..."` to a smaller value.
5. Run `autofix.py && iterate.py`.
6. Confirm with the user that the placement now matches their intent — they may want it even further left, or a different zone moved instead.

### Recovery loop (you regressed)

1. Last `iterate.py` showed `↓-2.5` — your edit broke something.
2. Use `git diff foo.drawio` (or your editor's undo) to inspect the exact change that hurt the score.
3. If the change was off the user's nudge path, undo it and try a smaller, more targeted version.
4. If the change WAS on the user's nudge path but the structural cost is high, explain the tradeoff to the user and ask whether they want the visual change or the score.

## When to stop

The loop terminates when ANY of these are true:

- `iterate.py` reports `score >= 90` AND the user has given no follow-up nudge.
- The user explicitly says "good", "stop", "ship it".
- Five consecutive iterations move the score by less than ±0.5 points (you're at a plateau — better to ask the user what to nudge next than to keep guessing).
- The user starts asking for changes that aren't SAP-style (custom dark backgrounds, novelty pill verbs the validator rejects). In that case acknowledge the tradeoff once and proceed.

## What `iterate.py` does NOT do

- It does not edit the diagram for you. You (the LLM) make all edits.
- It does not run Ollama. The LLM in Cursor / Claude Code IS the model — `iterate.py` just feeds it visual + scored feedback.
- It does not roll back automatically. Use git or your editor's undo for that.
- It does not change the target template mid-loop unless you re-invoke with `--target`. If you scaffolded from template A and are 30 iterations in, switching to template B will reset the score baseline.
