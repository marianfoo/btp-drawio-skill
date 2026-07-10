# Semantic Specification

Create the specification before template selection. It is the architecture contract used to stop a visually convincing but wrong diagram from passing.

## Schema

```json
{
  "schema_version": 1,
  "subject": "CAP application accessing SAP S/4HANA through Cloud Connector",
  "level": "L2",
  "required_zones": [
    {"name": "SAP BTP", "aliases": ["SAP BTP - Cloud Foundry"]},
    {"name": "Customer On-Premise Network", "aliases": ["On-Premise"]}
  ],
  "required_nodes": [
    {"name": "CAP application", "aliases": ["CAP Service", "Extension Application"]},
    {"name": "SAP Destination service", "aliases": ["Destination Service"]},
    {"name": "SAP Cloud Connector", "aliases": ["Cloud Connector"]},
    {"name": "SAP S/4HANA", "aliases": ["S/4HANA On-Premise"]}
  ],
  "required_flows": [
    {
      "from": {"name": "CAP application", "aliases": ["CAP Service"]},
      "to": {"name": "SAP Destination service", "aliases": ["Destination Service"]}
    },
    {
      "from": "SAP Cloud Connector",
      "to": {"name": "SAP S/4HANA", "aliases": ["S/4HANA On-Premise"]}
    }
  ],
  "required_terms": ["OData/REST", "Authenticate"],
  "forbidden_terms": ["Direct public internet access"],
  "provenance": {
    "allowed_raster_hashes": []
  }
}
```

## Matching Rules

- Strings match visible draw.io labels case-insensitively after HTML removal.
- An object adds aliases to the canonical name.
- `required_flows` are directional by default. Set `"bidirectional": true` only when direction is genuinely not material.
- Flow matching normally uses visible `source` and `target` labels. If the draw.io edge must remain attached to a pill, group, or helper shape to preserve the SAP route geometry, annotate the edge with `data-semantic-source="<canonical or alias label>"` and `data-semantic-target="<canonical or alias label>"`. These attributes affect semantic validation only; they do not change the visible diagram.
- `required_terms` prove notation or protocol presence anywhere in the first diagram page. They do not prove that a free-floating pill is attached to a specific edge; visual review must confirm that relationship.
- `forbidden_terms` catch preserved template content that the request explicitly excludes.
- Keep aliases narrow. Do not use generic aliases such as `service`, `system`, `cloud`, or `user` merely to make validation pass.

## Evidence Discipline

The specification records the requested or evidence-backed architecture. Label unsupported but useful working assumptions outside the JSON and keep the diagram at `internal-draft`. Do not convert template content into an architecture claim merely because SAP published the source template.

When the request changes, update the specification first and then the diagram. A gate failure is evidence of drift, not permission to weaken the contract.

## Raster Review

`provenance.py --audit --strict` flags small square embedded raster images because a copied QR code can be visually indistinguishable from a legitimate provider logo in XML metadata.

1. Render and inspect the image.
2. Identify each flagged raster.
3. Remove source QR/reference media.
4. Add only confirmed legitimate raster hashes to `provenance.allowed_raster_hashes`.

Never allow a hash without inspecting the corresponding rendered image.
