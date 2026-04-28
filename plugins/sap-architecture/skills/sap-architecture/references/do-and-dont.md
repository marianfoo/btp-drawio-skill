# Do and Don't — consolidated SAP rules

Every entry below is a verbatim quote from the official SAP BTP Solution Diagram Guidelines, with the source file in the footer of each item.

## Areas / containers

**DO** — alternate fill / no-fill when nesting:
> "When nesting different areas inside each other, you should alternate between using a fill and not using a fill to provide sufficient contrast between the areas. **The parent layer is usually the BTP layer.**" — `diagr_comp/areas.md`

**DON'T** — change the style of stacked layers:
> "Areas can be shown as stacked to display multiple grouped layers or items. **The style should not be changed in order to keep diagrams consistent.**" — `diagr_comp/areas.md`

**DO** — use the fixed corner radius:
> "**A fixed corner radius of 16 pixels is recommended.**" — `diagr_comp/areas.md`

## Color usage

**DO** — use one consistent palette family (Horizon):
> "Horizon is the default visual style for SAP Products … This also applies to diagrams." — `foundation.md`

**DON'T** — paint everything in accent colors:
> "Secondary colors can be applied to accentuate important elements. They make a vivid contribution to the overall UI and **should be used sparingly.**" — `foundation.md`

**DON'T** — overpower with primary/non-SAP either:
> "It is not recommended to use the colors too heavily, they can overpower the diagram." — `diagr_comp/areas.md`

## Connectors / arrows

**DO** — use the fixed semantic mapping:
> "Trust Flows are usually pink / Authentication flows are usually green / Authorization flows are usually indigo / Firewalls and Network barriers are thick grey lines" — `lines_connectors.md`

**DO** — pick the line style that matches the data-flow semantics:
> "Solid lines for direct, synchronous request-response data flows / Dashed lines for indirect, asynchronous data flows / Dotted lines for optional data flows / Thick lines for firewalls only" — `foundation.md`

**DON'T** — invent your own arrow style:
> "Avoid creating your own arrows; use the ones available in the library instead as they adhere to the correct styling guidelines." — `solution_diagr_intro/big_picture.md`

**DON'T** — use thick lines for anything other than firewalls:
> "Thick lines for firewalls only" — `foundation.md`

## Icons

**DO** — use the grey-circle service icons:
> "**For diagram visualization it is mandatory to use the version with grey background circle.**" — `diagr_comp/icons.md`

**DO** — use generic icons for non-SAP elements (devices, databases):
> "This set of icons with soft gradients is used for all elements that are either generic such as devices or databases. … **The primary color used is neutral grey.**" — `diagr_comp/icons.md`

## Product names

**DO** — pair SAP product names with the SAP logo:
> "**SAP product names must be paired with the SAP logo.**" — `diagr_comp/product_names.md`

**DON'T** — over-do the SAP logo:
> "**It is not recommended to use too many SAP logos in the same diagram. Use text only elements instead.**" — `diagr_comp/product_names.md`

The skill applies this rule by placing exactly **one** SAP logo per diagram (top-right of the BTP zone). Service cards inside the BTP zone don't get individual logos — the one zone-level logo carries them.

## Text / typography

**DO** — keep text sizes consistent when scaling:
> "When scaling elements up or down, take care to ensure text sizes remain consistent." — `solution_diagr_intro/big_picture.md`

**DO** — use the four-style hierarchy:
> "**To create hierarchies four text styles were derived from Fiori Horizon.**" — `diagr_comp/text.md`

## Spacing

**DO** — use the SAP-logo-height rule:
> "**Spacing around objects should be even and roughly the height of the SAP Logo.**" — `foundation.md`

## Legend

**DO** — include a legend in L1 / L2:
> "**Including a legend in each diagram is crucial to clarify these meanings.**" — `foundation.md`

**DON'T (L0 only)** — force a legend onto a marketing-level diagram:
> "In such diagrams, connectors maintain neutrality and the content is streamlined to essentials, **eliminating the necessity for a legend, but a short description is recommended.**" — `solution_diagr_intro/big_picture.md`

## PowerPoint vs draw.io

**DO** — switch to draw.io if PowerPoint constrains the layout:
> "**Slide dimensions are unalterable**, so if you find the available space inadequate for your diagram, **avoid downscaling all the elements to accommodate it**. … **If your diagram is too large for PowerPoint, consider switching to draw.io.**" — `solution_diagr_intro/big_picture.md`

This skill always emits draw.io.

## What this skill enforces automatically

`validate.py` catches:

- Off-palette hex (warns)
- `absoluteArcSize=1` missing when `arcSize` is set (warns; autofix repairs)
- `strokeWidth` outside `{1, 1.5, 2, 3, 4}` (warns)
- `strokeWidth>=3` flagged for review (firewall-only rule)
- Edge label without `labelBackgroundColor=default` (warns)
- Bent `orthogonalEdgeStyle` edge (centers not aligned on any axis) — error
- Label text wider than its shape — error
- Sibling shape overlap (not contained, not transparent, not pill) — error
- Off-grid coordinates — warns; autofix repairs
- `fontFamily` ≠ Helvetica — warns; autofix repairs
- Duplicate ids, missing `mxGeometry`, XML comments — error

What `validate.py` does **not** check (yet — manual review):

- "Use the grey-circle icon variant" — visual check, not extractable from XML
- "One SAP logo per diagram" — countable but currently not enforced
- "Don't use accent colors heavily" — proportional rule, hard to quantify
- "Spacing roughly = SAP logo height" — context-dependent
- "Legend present" — checked only via warning if `level=L1|L2` and no `legend` element exists
