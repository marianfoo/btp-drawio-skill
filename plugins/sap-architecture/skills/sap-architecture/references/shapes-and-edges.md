# Shape & edge conventions

All values match the SAP BTP Solution Diagram Guidelines and the actual `.drawio` files SAP ships in `SAP/btp-solution-diagrams` and `SAP/architecture-center`. Copy the style strings verbatim — never invent alternatives.

## Zone frame (outer landscape containers)

Every zone has an **inline top-left bold label** — never a separate header tab. Corner radius is fixed at 16 px:

> "**A fixed corner radius of 16 pixels is recommended.**"

— `diagr_comp/areas.md`

```
rounded=1;whiteSpace=wrap;html=1;arcSize=16;absoluteArcSize=1;strokeWidth=1.5;
fontFamily=Helvetica;align=left;verticalAlign=top;spacingLeft=10;spacingTop=10;
fontSize=16;fontStyle=1;
```

`arcSize=16;absoluteArcSize=1` produces a fixed 16-px corner radius. Without `absoluteArcSize=1`, draw.io interprets `16` as a percentage and on a 700-px-wide zone you get a 112-px radius. **`autofix.py` adds `absoluteArcSize=1` automatically, but your source should have it from the start.**

## Service card (tile inside a zone)

```
rounded=1;whiteSpace=wrap;html=1;arcSize=16;absoluteArcSize=1;strokeWidth=1.5;
fontFamily=Helvetica;fontSize=12;align=center;verticalAlign=middle;
```

Card content is HTML in the `value` attribute — bold title 13 px then `<br/>` then muted caption 11 px wrapped in `<span style="font-size:11px;color:#556B82;font-weight:normal;">…</span>`. Typical size: **280 × 50–84 px**.

### Icon + label pattern

For a BTP service tile with the official icon + a label underneath, use the pre-built mxCell from the bundled library (see `extract_icon.py`). The library cells already set:

- `shape=image;image=data:image/svg+xml,<base64>`
- `verticalLabelPosition=bottom;verticalAlign=top` — puts the label below the icon
- `labelPosition=center;align=center`
- `imageAspect=0;aspect=fixed`

Default size **64 × 80** (icon 64 px + ~16 px for the label). Set `fontSize=12` on the icon cell for the label — larger than the ref default 10 so short labels don't look stranded.

> "**For diagram visualization it is mandatory to use the version with grey background circle.**"

— `diagr_comp/icons.md`

The bundled library is the grey-circle variant. Don't substitute plain SVGs.

## Action pill (edge pill — HTTPS, TRUST, Sign-in, mTLS, A2A, MCP, authorization)

```
rounded=1;whiteSpace=wrap;html=1;arcSize=50;absoluteArcSize=1;strokeWidth=1;
fontFamily=Helvetica;fontSize=10;align=center;verticalAlign=middle;
```

- **Size**: 60–90 × 20–24 px
- **Label**: `<b style="font-size:10px;">LABEL</b>` — short, imperative, UPPERCASE for trust relationships
- **Color per role** — see "Edge color semantics" below

Pills **float on top** of zone frames — they share `parent="1"` with the zones, not the zone as parent. The validator suppresses overlap warnings for them.

## Numbered flow step (L1/L2 flow narration)

Small coloured circle (`shape=ellipse;aspect=fixed`), ~28-35 px diameter, with a single-digit bold label. Color matches the semantic category (green = auth step, indigo = authz step, magenta/pink = trust step, neutral `#475E75` = plain flow step).

## Edge defaults

```
edgeStyle=orthogonalEdgeStyle;rounded=0;html=1;
strokeColor=#475E75;strokeWidth=1.5;
endArrow=blockThin;endSize=6;endFill=1;
fontFamily=Helvetica;fontSize=10;
labelBackgroundColor=default;
```

**`labelBackgroundColor=default` is mandatory** for any edge that crosses a filled zone. Without it, edge label text bleeds into the `#EBF8FF` BTP fill and becomes unreadable — the single most common "looks unpolished" bug. The validator flags this.

> "Avoid creating your own arrows; use the ones available in the library instead as they adhere to the correct styling guidelines."

— `solution_diagr_intro/big_picture.md`

The `endArrow=blockThin;endSize=6;endFill=1` style above matches the SAP-shipped library arrows.

### Edge color semantics — **the SAP-mandated mapping**

> "To harmonize certain reoccurring flows a use of the following standards is recommended:
> - **Trust Flows are usually pink**
> - **Authentication flows are usually green**
> - **Authorization flows are usually indigo**
> - **Firewalls and Network barriers are thick grey lines**"

— `lines_connectors.md`

| Color | Meaning | Stroke / Fill (when used as pill) |
|-------|---------|-----------------------------------|
| `#475E75` | Default internal flow | — |
| `#188918` | **Authentication** (positive semantic) | stroke `#188918`, fill `#F5FAE5`, text `#266F3A` |
| `#5D36FF` | **Authorization** (indigo accent) | stroke `#5D36FF`, fill `#F1ECFF` |
| `#CC00DC` dashed | **Trust relationship** (pink accent, no data) | stroke `#CC00DC`, fill `#FFF0FA` |
| `#07838F` | **Custom emphasis** (teal — e.g. MCP tool call) | stroke `#07838F`, fill `#DAFDF5` |
| `#000000` solid thick (`strokeWidth=3` or `4`) | Network / firewall barrier | — |
| `#002A86` | Call into SAP ABAP system (ADT) | — |

### Line-style semantics

> "Recommended styles for BTP Solution Diagrams are:
> - Solid lines for direct, synchronous request-response data flows
> - Dashed lines for indirect, asynchronous data flows
> - Dotted lines for optional data flows
> - Thick lines for firewalls only"

— `foundation.md`

| Style | draw.io flags | Meaning |
|-------|---------------|---------|
| **Solid** | (default) | Direct, synchronous request-response |
| **Dashed** | `dashed=1;dashPattern=4 4` | Indirect, asynchronous |
| **Dotted** | `dashed=1;dashPattern=1 4` | Optional |
| **Thick** | `strokeWidth=3` or `4` | Firewall / network barrier (only — never for emphasis) |

### Trust lines

Use `dashed=1;dashPattern=4 4` for trust relationships:

```
edgeStyle=orthogonalEdgeStyle;rounded=0;html=1;
strokeColor=#CC00DC;strokeWidth=1.5;
dashed=1;dashPattern=4 4;
endArrow=none;startArrow=none;
fontFamily=Helvetica;fontSize=10;
labelBackgroundColor=default;
```

Mutual trust → no arrowheads (`startArrow=none;endArrow=none`).

> "Bidirectional solid arrows may represent mutual trust."

— `lines_connectors.md`

(Bidirectional arrows for trust **without** dashing are also acceptable per the doc, but the dashed variant is more visually distinct from data flows. The skill defaults to dashed.)

## Alignment rule — the highest-leverage polish trick

For an `orthogonalEdgeStyle` edge with `source=A; target=B` to render as a **straight line** (no bend), the **centers** of A and B must share an axis:

- `A.centerX == B.centerX` → vertical straight line
- `A.centerY == B.centerY` → horizontal straight line

Where `centerX = x + width/2`, `centerY = y + height/2`.

If the centers differ on both axes, the edge renders with a 90° kink. Either:

1. Snap one coordinate so the centers align (preferred), **or**
2. Add explicit docking anchors: `entryX=0.5;entryY=0;exitX=0.5;exitY=1;entryDx=0;entryDy=0;exitDx=0;exitDy=0`.

`validate.py` detects this class of bug and reports `edge N: source/target centers differ on both axes`.

## Spacing — the SAP-logo heuristic

> "**Spacing around objects should be even and roughly the height of the SAP Logo.**"

— `foundation.md`

The SAP logo (the 60 × 23 px library shape) is ~23 px tall, snap-rounded → use **20 px** between sibling cards and **30 px** between zones.

## Gotchas

- **Widths like `239.99999999999997`** happen because draw.io UI rounds imprecisely — emit integers. `autofix.py` quantises them.
- **`absoluteArcSize=1` is non-negotiable** — without it `arcSize=16` on an 800-px zone makes a 128-px radius.
- **Pill `strokeWidth` is `1`, not `1.5`** — pills are small and 1.5 looks over-weighted.
- **Edge labels need `labelBackgroundColor=default`** even when the edge is outside a zone, for consistency.
- **Service-card labels are set on the icon cell**, not the wrapping rectangle. Naive generators put the label on the rectangle and the text gets clipped by the icon image.
- **Don't use thick lines for emphasis.** Thick = firewall only. The validator warns on `strokeWidth>=3` outside a firewall context.
- **Don't recolour library arrows** — use the ones from the library and only change the `strokeColor` to the semantic color (green/indigo/pink/teal/grey).
