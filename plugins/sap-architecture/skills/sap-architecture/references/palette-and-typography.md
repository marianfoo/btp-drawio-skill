# SAP Horizon palette & typography

Every value in this file is sourced from the **official SAP BTP Solution Diagram Guidelines** at https://github.com/SAP/btp-solution-diagrams/tree/main/guideline. Quotes are verbatim. Hex values are normalised to uppercase (autofix.py will normalise any surviving lowercase).

## The atomic design system

Quoted from `guideline/docs/btp_guideline/atomic.md`:

> "Atoms are the smallest elements – in this case the basic elements such as colors, line styles, icons, and text"
>
> "Molecules are elements that consist of atoms. A Molecule refers to any element that uses the basic colors and lines, for example, an arrow that is red and dashed."
>
> "Organisms are groups of Molecules. This could be grouped elements such as a typical shape with text and connectors, or even a whole diagram."

This skill emits at the organism level — composed zones with cards, connectors, and pills — but every value below is at the atom level so that nothing improvises.

## Color philosophy

> "Horizon is the default visual style for SAP Products. Its color balance helps to draw the user's attention to the essential information and functions. It also promotes a distinct and consistent look throughout all products. **This also applies to diagrams.**"

— `foundation.md`

The skill never invents palette values. The `validate.py` check warns on any hex outside this file.

## Primary palette — the everyday colors

| Role | Border | Fill | Source |
|------|--------|------|--------|
| **SAP / BTP area** | `#0070F2` | `#EBF8FF` | `foundation.md` |
| **Non-SAP area** | `#475E75` | `#F5F6F7` | `foundation.md` |
| **Title text** | — | — | `#1D2D3E` (`foundation.md`) |
| **Body text** | — | — | `#556B82` (`foundation.md`) |

> "Blue is the standard, grey for non-sap elements and the Accent colors are for highlighting certain areas."
>
> "It is not recommended to use the colors too heavily, they can overpower the diagram."

— `diagr_comp/areas.md`

## Semantic palette — status / meaning

> "Semantic colors can be used to represent a negative, critical, positive, neutral, or information status."

— `foundation.md`

| Role | Border | Fill |
|------|--------|------|
| **Positive** (authentication, mTLS, success) | `#188918` | `#F5FAE5` |
| **Critical** (warnings, partial outage) | `#C35500` | `#FFF8D6` |
| **Negative** (errors, blocked) | `#D20A0A` | `#FFEAF4` |

## Accent palette — sparingly, for emphasis

> "Secondary colors can be applied to accentuate important elements. They make a vivid contribution to the overall UI and **should be used sparingly.**"

— `foundation.md`

| Role | Border | Fill |
|------|--------|------|
| **Teal** (MCP, custom emphasis) | `#07838F` | `#DAFDF5` |
| **Indigo** (authorization flows, focus app) | `#5D36FF` | `#F1ECFF` |
| **Pink** (trust flows) | `#CC00DC` | `#FFF0FA` |

The semantic mapping for connectors is fixed (see `shapes-and-edges.md`):

> "To harmonize certain reoccurring flows a use of the following standards is recommended:
> - Trust Flows are usually pink
> - Authentication flows are usually green
> - Authorization flows are usually indigo
> - Firewalls and Network barriers are thick grey lines"

— `lines_connectors.md`

## Color proportion — the area-color rule

> "It is not recommended to use the colors too heavily, they can overpower the diagram."

The published SAP examples observe roughly:

- **~70%** primary blue (SAP / BTP zones, service cards) and neutral grey (non-SAP)
- **~20%** white inner frames (subaccount, runtime container, focus app)
- **~10%** accent (one or two colored zones / pills max)

Don't paint two zones in different accent colors competing for attention. If two flows need to be highlighted, use one accent and keep the rest neutral.

## Alternating fill by nesting level

> "When nesting different areas inside each other, you should alternate between using a fill and not using a fill to provide sufficient contrast between the areas. **The parent layer is usually the BTP layer.**"

— `diagr_comp/areas.md`

Resulting pattern (alternation, parent = BTP):

| Nest level | Fill |
|------------|------|
| L0 outer (BTP) | `#EBF8FF` |
| L1 inner | `#FFFFFF` (no fill) |
| L2 inner | `#EBF8FF` |
| L3 inner | `#FFFFFF` |

Stacked layers (e.g. multi-tenant subaccounts) keep the same style:

> "Areas can be shown as stacked to display multiple grouped layers or items. **The style should not be changed in order to keep diagrams consistent.**"

— `diagr_comp/areas.md`

## Typography — Helvetica everywhere

The guideline document mentions Arial and Arial Black as font choices:

> "To add the system fonts Arial and ArialBlack to your local draw.io installation you can add the following to the configuration: `{ "customFonts": ["Arial", "Arial Black"] }`"

— `solution_diagr_intro/intro.md`

**However**, every published SAP `.drawio` file under `assets/editable-diagram-examples/` and every reference architecture under `SAP/architecture-center/docs/ref-arch/` ships with **`fontFamily=Helvetica`** — that's the actual de-facto value. The skill follows the shipped files: emit Helvetica, autofix to Helvetica. The "Arial" advice in `intro.md` is about adding it as an *available* custom font in your draw.io install, not about changing the diagrams themselves.

### Hierarchy

> "**To create hierarchies four text styles were derived from Fiori Horizon.**"

— `diagr_comp/text.md`

The doc commits the four styles only via a graphic (`text_styles.png`); concrete pt sizes derived from observation of the shipped templates:

| Role | Size (pt) | Weight (`fontStyle`) | Color |
|------|-----------|----------------------|-------|
| Diagram title | 24 | bold (`1`) | `#1D2D3E` |
| Subtitle | 14 | regular (`0`) | `#475E75` |
| Zone / container label | 16 | bold (`1`) | `#475E75` (non-SAP) or `#1D2D3E` / `#00185A` (BTP) |
| Feature-group heading inside a card | 18 | bold (`1`) | `#1D2D3E` |
| Sub-section label | 14 / 11 | bold (`1`) | accent or `#1D2D3E` |
| Service card title | 12–14 | bold (`1`) | `#1D2D3E` |
| Service card caption / inline helper | 11 | regular (`0`) | `#556B82` |
| Pill label | 10 | bold (`1`) — uppercase for TRUST | pill text color |
| Edge label | 10 | regular (`0`) | `#475E75` or zone color |

Never use pure black. `#1D2D3E` reads as "black" but harmonises with the blue zone fills.

### Scaling rule

> "Texts defined in this document may need to be scaled up to fit the specifications of the target medium."
>
> "When scaling elements up or down, take care to ensure text sizes remain consistent."

— `text.md` and `solution_diagr_intro/big_picture.md`

If the user asks for a poster-sized canvas, scale the **whole** diagram including text — don't tweak font sizes individually.

## Spacing — the SAP-logo heuristic

> "**Spacing around objects should be even and roughly the height of the SAP Logo.**"

— `foundation.md`

The SAP logo (the standard 60 × 23 px draw.io shape) is roughly **23 px tall**, snapped to the 10-px grid that's **20 px** of breathing room. Use 20 px between sibling cards, 30 px between zones.

## Banned palettes

Not in the SAP Horizon family — the validator flags these as warnings:

- draw.io defaults: `#dae8fc`, `#d5e8d4`, `#f8cecc`, `#6c8ebf`, `#fff2cc`
- Material / Tailwind generic pastels
- Pure `#000000` for text (use `#1D2D3E` instead)
- Any hex not listed in `validate.py:SAP_PALETTE`

## Don't

> "It is not recommended to use too many SAP logos in the same diagram. Use text only elements instead."

— `diagr_comp/product_names.md`

> "**SAP product names must be paired with the SAP logo.**" *(but only one logo per zone, not one per service card)*

— `diagr_comp/product_names.md`

> "Avoid creating your own arrows; use the ones available in the library instead as they adhere to the correct styling guidelines."

— `solution_diagr_intro/big_picture.md`
