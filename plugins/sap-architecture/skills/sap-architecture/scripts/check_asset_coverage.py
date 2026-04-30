#!/usr/bin/env python3
"""Smoke-check SAP library and palette coverage.

This is intentionally fast and local. It verifies that the LLM-facing indexes
cover the bundled SAP draw.io libraries and that the validator accepts every
official SAP preset color from drawio-config-all-in-one.json.
"""
from __future__ import annotations

import json
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

from build_asset_index import LIBRARY_KINDS
from extract_asset import emit_asset
from validate import SAP_PALETTE

HERE = Path(__file__).resolve().parent
ASSETS = HERE.parent / "assets"
LIB_DIR = ASSETS / "libraries"
ICON_INDEX = ASSETS / "icon-index.json"
ASSET_INDEX = ASSETS / "asset-index.json"

OFFICIAL_PRESET_COLORS = {
    "#0070F2",
    "#EBF8FF",
    "#475E75",
    "#F5F6F7",
    "#1D2D3E",
    "#556B82",
    "#188918",
    "#F5FAE5",
    "#C35500",
    "#FFF8D6",
    "#D20A0A",
    "#FFEAF4",
    "#07838F",
    "#DAFDF5",
    "#5D36FF",
    "#793802",
    "#F1ECFF",
    "#CC00DC",
    "#FFF0FA",
}


class Args:
    x = 0
    y = 0
    w = None
    h = None
    id = "smoke"
    parent = "1"
    label = None


def fail(message: str) -> int:
    print(f"FAIL: {message}", file=sys.stderr)
    return 1


def main() -> int:
    missing = [name for name in LIBRARY_KINDS if not (LIB_DIR / name).exists()]
    if missing:
        return fail(f"missing libraries: {', '.join(missing)}")

    icon_index = json.loads(ICON_INDEX.read_text(encoding="utf-8"))
    asset_index = json.loads(ASSET_INDEX.read_text(encoding="utf-8"))
    assets = asset_index["assets"]

    service_assets = [a for a in assets.values() if a["kind"] == "btp-service-icon"]
    if len(icon_index) != len(service_assets):
        return fail(f"icon-index has {len(icon_index)} entries but asset-index has {len(service_assets)} service icons")
    if "sap-build" not in icon_index:
        return fail("SAP Build is missing from icon-index")
    if not any(key == "btp-service-icon:sap-build" for key in assets):
        return fail("SAP Build is missing from asset-index")

    expected_count = sum(meta["entries"] for meta in asset_index["metadata"]["libraries"].values())
    actual_count = asset_index["metadata"]["count"]
    if actual_count != expected_count or actual_count != len(assets):
        return fail(f"asset count mismatch: metadata={actual_count}, library sum={expected_count}, assets={len(assets)}")

    missing_palette = OFFICIAL_PRESET_COLORS - {color.upper() for color in SAP_PALETTE}
    if missing_palette:
        return fail(f"validator missing official SAP colors: {sorted(missing_palette)}")

    smoke_keys = [
        "btp-service-icon:sap-build",
        "btp-service-icon:sap-authorization-and-trust-management-service",
        "generic-icon:devices-non-sap",
        "connector:direct-one-directional",
        "area-shape:area-shapes-dashed",
        "number-marker:1",
        "sap-brand-name:sap-btp",
        "annotation-interface:interface",
    ]
    for key in smoke_keys:
        asset = assets.get(key)
        if not asset:
            return fail(f"smoke asset missing: {key}")
        xml = emit_asset(asset, Args())
        ET.fromstring(f"<root>{xml}</root>")

    print(f"ok: {len(icon_index)} BTP service icons")
    print(f"ok: {actual_count} indexed SAP draw.io assets across {len(asset_index['metadata']['libraries'])} libraries")
    print(f"ok: {len(OFFICIAL_PRESET_COLORS)} official SAP preset colors covered")
    return 0


if __name__ == "__main__":
    sys.exit(main())
