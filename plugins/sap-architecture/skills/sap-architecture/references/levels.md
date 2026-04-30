# SAP BTP Solution Diagram levels

The SAP BTP Solution Diagram Guidelines document **three levels — L0, L1, L2**. L3 is mentioned once in passing (`L0 — L2/L3 presentations`) but is **not specified** anywhere in the official guideline. Treat L3 as unofficial; default to **L2** when the user doesn't specify.

Source for everything below: `guideline/docs/solution_diagr_intro/big_picture.md`.

## The three documented levels

| Level | Audience | Shows | Hides | Typical shapes |
|-------|----------|-------|-------|----------------|
| **L0 — Marketing / overview** | Business roles, sales, business architects, enterprise architects, IT managers, IT analysts, CTOs. *("simply require an overview … rudimentary technical knowledge")* | One concept per box. Logos, neutral arrows, outcome wording. **No legend required**, but a short description is recommended. | Anything technical. | 3–6 hero cards, simplified flows. |
| **L1 — Conceptual** | Enterprise / solution architects, SAP consultants, product managers, presales, use case owners, DC mission owners. *("strong technical acumen and interest")* | Named SAP services, trust zones, coarse data flow. | Protocol names, hostnames, auth details. | Service cards grouped by zone (BTP vs on-prem), plain arrows. |
| **L2 — Logical / technical** *(default)* | SAP solution architects, cloud architects, product managers, business + dev roles, consultants, technical presales. *("extensive technical understanding, requiring detailed information")* | Services, accounts, roles, protocols, trust/auth pills, **legend mandatory**. | Hostnames, subnets, cert names. | Full 3–4 zone landscape with semantic pills on edges. |

Verbatim audience quotes from `big_picture.md`:

> "**L0 diagrams target individuals who simply require an overview.** They typically possess just rudimentary technical knowledge and interest."
>
> "**L1 diagrams target Individuals who possess a strong technical acumen and interest.** They often participate in technical decision-making processes."
>
> "**L2 diagrams target individuals with an extensive technical understanding, requiring detailed information to inform their decision-making process.**"

## L0 specifics

> "The granularity of diagrams should be adjusted according to the expertise of the intended audience. For example, the broadest level of detail, Level 0, caters mainly to individuals with basic technical skills, such as those in business roles."
>
> "A representative example would be a high-level solution diagram featuring BTP Services and simplified flows, without complex technical details. **In such diagrams, connectors maintain neutrality** and the content is streamlined to essentials, **eliminating the necessity for a legend, but a short description is recommended.**"

— `big_picture.md`

L0 implications for the skill:

- Connector colors → all neutral grey (`#475E75`); no semantic auth/trust/authz colors.
- No edge pills.
- ≤ 6 service cards on canvas.
- Skip the legend block.
- Add a short description text element below the canvas instead.

## L1 specifics

- Group services by area (BTP, On-Prem, Third Party). Solid arrows for direct flow.
- Named SAP services with the grey-circle service icon.
- Optional: numbered step indicators (1 → 2 → 3) along the main flow.
- Legend optional but recommended.

## L2 specifics (the default for this skill)

- All four zones (User, BTP, On-Prem, Third-Party) where applicable.
- Numbered semantic pills on edges (TRUST, SIGN-IN, OAUTH · JWT, mTLS · PP, MCP TOOL CALL, …).
- Legend **mandatory** in principle — explains pill colors and line styles. If the selected SAP reference template has no separate legend block but already uses labelled inline pills, preserve that template structure and put the legend explanation in the generated flow narration instead of adding a new bottom band.
- Inline service icons (grey-circle variant only — see `diagr_comp/icons.md`).

> "Including a legend in each diagram is crucial to clarify these meanings."

— `foundation.md`

## What about L3?

L3 is **not documented**. If a user explicitly asks for L3 (typical signals: hostnames, CIDRs, cert names, CIDR blocks, NAT gateway IPs, "production deployment", "rollout" details), proceed but produce an L2 with extra annotations rather than a different visual style. Tell the user the diagram is "L2 with physical annotations" — don't claim it follows an SAP-defined L3 spec.

## Canvas & tab naming

- Use `pageWidth="1169" pageHeight="827"` for new diagrams unless the selected SAP reference template uses a different size. The 2026 corpus includes larger landscape and portrait variants; preserving the chosen template's canvas scores better than normalising every diagram to one size.
- `grid="1" gridSize="10"` — show the grid while authoring, snap everything to 10 px.
- `<diagram name="…">` tab stem matches the output filename, suffixed with the level: `Product_Name_L2`, `ARC1_BTP_Deployment_L2`.
- `page="1"`, `pageScale="1"`, `math="0"`, `shadow="0"`, `background="none"` (default white).

## Flow narration

Numbered flow steps (1 → 2 → 3 …) are drawn as **small coloured circular pills on the diagram** (see `shapes-and-edges.md`). The full prose ("Step 1: User signs in to SAP Cloud Identity Services…") lives **below the embedded image** in the host document (Markdown / Confluence), **not** in a text block inside the canvas. This mirrors `architecture.learning.sap.com` — the canvas stays clean, the page carries the narrative.

When the output is a standalone `.drawio` (no host document), the skill prints the flow narration to stdout at the end of the run so the user can paste it into their docs.
