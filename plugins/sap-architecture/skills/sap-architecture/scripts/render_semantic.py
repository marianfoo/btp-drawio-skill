#!/usr/bin/env python3
"""Render a SAP-style architecture diagram from a small semantic archetype.

This is the escape hatch for prompts where nearest-template copying is known to
hit a geometry ceiling. It deliberately supports only a few SAP BTP archetypes;
unknown prompts should still go through scaffold_diagram.py.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

THIS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(THIS_DIR))

try:
    import extract_icon  # type: ignore[import-not-found]
except Exception:  # pragma: no cover - renderer still works without icons
    extract_icon = None


BLUE = "#0070F2"
TEXT = "#1D2D3E"
MUTED = "#475E75"
AUTH_GREEN = "#188918"
ZONE_FILL = "#EBF8FF"
NEUTRAL_FILL = "#F5F6F7"
WHITE = "#FFFFFF"
PILL_FILL = "#FCFCFC"
PAGE_W = 1169
PAGE_H = 827


@dataclass(frozen=True)
class Box:
    id: str
    label: str
    x: int
    y: int
    w: int
    h: int
    icon: str | None = None
    fill: str = WHITE
    stroke: str = BLUE


@dataclass(frozen=True)
class Edge:
    id: str
    source: str
    target: str
    label: str = ""
    stroke: str = MUTED


@dataclass(frozen=True)
class Pill:
    id: str
    label: str
    x: int
    y: int
    w: int = 120
    h: int = 24


@dataclass(frozen=True)
class DiagramPlan:
    archetype: str
    title: str
    subtitle: str
    width: int
    height: int
    boxes: list[Box]
    edges: list[Edge]
    pills: list[Pill]
    zones: list[Box]


def norm(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip())


def words(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", text.lower()))


def snap(value: int | float) -> int:
    return int(round(float(value) / 10.0) * 10)


def infer_archetype(description: str) -> str:
    tokens = words(description)
    joined = " ".join(tokens)
    if tokens & {"siem", "soar", "threat", "etd"} or "security operations" in description.lower():
        return "security-operations"
    if tokens & {"devops", "cicd", "pipeline", "transport"}:
        return "devops"
    if tokens & {"privatelink", "private", "connector", "cloudconnector"}:
        return "private-connectivity"
    if tokens & {"a2a", "b2b", "b2g", "api", "integration", "eventmesh"}:
        return "integration-flow"
    if tokens & {"joule", "agentic", "agents", "mcp", "llm"} or "ai agent" in joined:
        return "ai-agent"
    return "generic-btp"


def title_from(description: str, archetype: str) -> str:
    clean = norm(description)
    if len(clean) <= 86:
        return clean
    defaults = {
        "security-operations": "Security Operations with SAP ETD and SOAR",
        "devops": "DevOps on SAP BTP",
        "private-connectivity": "Private Connectivity on SAP BTP",
        "integration-flow": "Integration Flow on SAP BTP",
        "ai-agent": "AI Agents on SAP BTP",
    }
    return defaults.get(archetype, "SAP BTP Architecture")


def security_operations(description: str) -> DiagramPlan:
    title = title_from(description, "security-operations")
    boxes = [
        Box("s4", "SAP S/4HANA\nOn-Premise Solutions", 40, 145, 250, 72, "sap s/4hana"),
        Box("rise", "RISE", 40, 235, 250, 72, None),
        Box("cloud", "SAP Cloud\nSolutions", 40, 325, 250, 72, "cloud foundry"),
        Box("btp", "SAP BTP", 40, 415, 250, 72, None),
        Box("resources", "Cloud Enterprise Resources\n(Network Logs, EDR, IAM, etc)", 560, 40, 300, 70, None),
        Box("etd", "SAP Domain Detection\n\nSAP Enterprise Threat Detection\n(Cloud Edition)", 440, 280, 240, 170, "audit log"),
        Box("analytics", "Central Security\nAnalytics\n\nFortiSIEM", 800, 250, 220, 170, None, NEUTRAL_FILL, MUTED),
        Box("response", "Security Orchestration\n& Response\n\nFortiSOAR", 800, 520, 220, 170, None, NEUTRAL_FILL, MUTED),
        Box("notification", "Notification System", 720, 725, 170, 50, None, WHITE, MUTED),
        Box("itsm", "ITSM System", 930, 725, 150, 50, None, WHITE, MUTED),
    ]
    edges = [
        Edge("e1", "s4", "etd"),
        Edge("e2", "rise", "etd"),
        Edge("e3", "cloud", "etd"),
        Edge("e4", "btp", "etd"),
        Edge("e5", "resources", "analytics"),
        Edge("e6", "etd", "analytics"),
        Edge("e7", "analytics", "response"),
        Edge("e8", "response", "notification"),
        Edge("e9", "response", "itsm"),
    ]
    pills = [
        Pill("p1", "Security Logs", 325, 335, 110, 24),
        Pill("p2", "Alerts, findings &\nenriched events", 680, 335, 135, 36),
        Pill("p3", "Correlated\nIncidents", 830, 455, 100, 38),
        Pill("p4", "Status & closure\nupdates", 930, 455, 110, 38),
        Pill("p5", "Notification", 740, 695, 125, 24),
        Pill("p6", "Open Ticket", 940, 695, 125, 24),
    ]
    return DiagramPlan(
        "security-operations",
        title,
        "L2 event-to-response flow for SAP and enterprise security signals",
        1100,
        850,
        boxes,
        edges,
        pills,
        [],
    )


def devops(description: str) -> DiagramPlan:
    title = title_from(description, "devops")
    zones = [
        Box("z-source", "Source and Build", 60, 130, 325, 515, None, ZONE_FILL, BLUE),
        Box("z-transport", "Transport and Release", 420, 130, 300, 515, None, ZONE_FILL, BLUE),
        Box("z-runtime", "SAP BTP Runtime", 755, 130, 340, 515, None, ZONE_FILL, BLUE),
    ]
    boxes = [
        Box("dev", "Developer", 115, 210, 165, 62, None),
        Box("git", "Git Repository", 115, 330, 165, 62, None),
        Box("cicd", "SAP Continuous\nIntegration and Delivery", 80, 455, 250, 82, "continuous integration and delivery"),
        Box("ctms", "SAP Cloud Transport\nManagement", 465, 300, 210, 82, "cloud transport management"),
        Box("alm", "SAP Cloud ALM", 465, 465, 210, 72, None),
        Box("cf", "Cloud Foundry\nRuntime", 815, 215, 200, 72, "cloud foundry"),
        Box("kyma", "Kyma Runtime", 815, 350, 200, 72, None),
        Box("abap", "ABAP Environment", 815, 485, 200, 72, "abap environment"),
    ]
    edges = [
        Edge("e1", "dev", "git"),
        Edge("e2", "git", "cicd"),
        Edge("e3", "cicd", "ctms"),
        Edge("e4", "ctms", "cf"),
        Edge("e5", "ctms", "kyma"),
        Edge("e6", "ctms", "abap"),
        Edge("e7", "alm", "ctms"),
    ]
    pills = [
        Pill("p1", "Commit", 155, 292, 82, 22),
        Pill("p2", "Build & Test", 145, 418, 105, 22),
        Pill("p3", "Release", 350, 420, 82, 22),
        Pill("p4", "Deploy", 720, 245, 82, 22),
        Pill("p5", "Deploy", 720, 380, 82, 22),
        Pill("p6", "Deploy", 720, 515, 82, 22),
    ]
    return DiagramPlan("devops", title, "L2 pipeline from source to SAP BTP runtimes", PAGE_W, PAGE_H, boxes, edges, pills, zones)


def private_connectivity(description: str) -> DiagramPlan:
    title = title_from(description, "private-connectivity")
    zones = [
        Box("z-btp", "SAP BTP", 170, 100, 700, 570, None, ZONE_FILL, BLUE),
        Box("z-network", "Private Network / Hyperscaler", 905, 170, 225, 360, None, NEUTRAL_FILL, MUTED),
    ]
    boxes = [
        Box("client", "Application Clients", 30, 325, 140, 62, None),
        Box("app", "Extension Application\n(CAP / HTML5)", 245, 280, 225, 92, "cloud application programming"),
        Box("dest", "SAP Destination\nservice", 540, 280, 155, 72, "destination"),
        Box("identity", "SAP Cloud Identity\nServices", 335, 565, 250, 72, None),
        Box("plink", "SAP Private Link\nservice", 710, 280, 150, 72, None),
        Box("provider", "Provider Service\nor SAP workload", 945, 280, 160, 92, None),
    ]
    edges = [
        Edge("e1", "client", "app"),
        Edge("e2", "app", "dest"),
        Edge("e3", "dest", "plink"),
        Edge("e4", "plink", "provider"),
        Edge("e5", "identity", "app", stroke=AUTH_GREEN),
    ]
    pills = [
        Pill("p1", "HTTPS", 178, 345, 70, 22),
        Pill("p2", "REST/OData", 452, 250, 95, 22),
        Pill("p3", "Private Link", 855, 245, 105, 22),
        Pill("p4", "Authenticate", 455, 505, 115, 22),
    ]
    return DiagramPlan("private-connectivity", title, "L2 private connectivity pattern for SAP BTP", PAGE_W, PAGE_H, boxes, edges, pills, zones)


def integration_flow(description: str) -> DiagramPlan:
    title = title_from(description, "integration-flow")
    zones = [
        Box("z-senders", "Sender Systems", 55, 150, 255, 470, None, NEUTRAL_FILL, MUTED),
        Box("z-btp", "SAP BTP - Integration Suite", 360, 110, 430, 550, None, ZONE_FILL, BLUE),
        Box("z-receivers", "Receiver Systems", 850, 150, 255, 470, None, NEUTRAL_FILL, MUTED),
    ]
    boxes = [
        Box("sender1", "SAP S/4HANA", 95, 250, 170, 62, None),
        Box("sender2", "Third-party\nApplication", 95, 390, 170, 72, None),
        Box("cpi", "Cloud Integration", 470, 230, 210, 72, "integration suite"),
        Box("api", "API Management", 470, 370, 210, 72, None),
        Box("event", "Event Mesh", 470, 510, 210, 72, "event mesh"),
        Box("receiver1", "SAP Cloud\nSolution", 895, 260, 170, 72, None),
        Box("receiver2", "Partner / B2B\nSystem", 895, 430, 170, 72, None),
    ]
    edges = [
        Edge("e1", "sender1", "cpi", "OData/REST"),
        Edge("e2", "sender2", "api", "API"),
        Edge("e3", "cpi", "receiver1", "Process Integration"),
        Edge("e4", "api", "receiver2", "Managed API"),
        Edge("e5", "event", "receiver1", "Events"),
    ]
    pills = [
        Pill("p1", "OData/REST", 310, 260, 105, 22),
        Pill("p2", "API", 315, 400, 70, 22),
        Pill("p3", "Events", 720, 530, 82, 22),
    ]
    return DiagramPlan("integration-flow", title, "L2 integration pattern with SAP Integration Suite", PAGE_W, PAGE_H, boxes, edges, pills, zones)


def ai_agent(description: str) -> DiagramPlan:
    title = title_from(description, "ai-agent")
    zones = [
        Box("z-user", "Users and Channels", 45, 155, 220, 430, None, NEUTRAL_FILL, MUTED),
        Box("z-btp", "SAP BTP", 315, 100, 455, 560, None, ZONE_FILL, BLUE),
        Box("z-sap", "SAP Cloud and Enterprise Systems", 835, 155, 280, 430, None, NEUTRAL_FILL, MUTED),
    ]
    boxes = [
        Box("user", "Business User", 80, 265, 150, 62, None),
        Box("joule", "SAP Joule", 385, 195, 180, 72, "joule"),
        Box("agent", "AI Agent /\nOrchestrator", 385, 330, 180, 82, None),
        Box("mcp", "MCP / Tool\nGateway", 575, 330, 160, 82, None),
        Box("identity", "SAP Cloud Identity\nServices", 400, 530, 250, 72, None),
        Box("s4", "SAP S/4HANA", 880, 240, 190, 62, None),
        Box("sf", "SAP SuccessFactors", 880, 355, 190, 62, None),
        Box("ext", "Third-party APIs", 880, 470, 190, 62, None),
    ]
    edges = [
        Edge("e1", "user", "joule"),
        Edge("e2", "joule", "agent"),
        Edge("e3", "agent", "mcp"),
        Edge("e4", "mcp", "s4"),
        Edge("e5", "mcp", "sf"),
        Edge("e6", "mcp", "ext"),
        Edge("e7", "identity", "agent", stroke=AUTH_GREEN),
    ]
    pills = [
        Pill("p1", "HTTPS", 270, 245, 80, 22),
        Pill("p2", "MCP", 545, 300, 70, 22),
        Pill("p3", "REST", 760, 492, 70, 22),
        Pill("p4", "Authenticate", 545, 455, 115, 22),
    ]
    return DiagramPlan("ai-agent", title, "L2 AI agent pattern with SAP BTP tools and identity", PAGE_W, PAGE_H, boxes, edges, pills, zones)


def generic_btp(description: str) -> DiagramPlan:
    return integration_flow(description)


PLANNERS = {
    "security-operations": security_operations,
    "devops": devops,
    "private-connectivity": private_connectivity,
    "integration-flow": integration_flow,
    "ai-agent": ai_agent,
    "generic-btp": generic_btp,
}


def icon_style(query: str | None) -> str | None:
    if not query or extract_icon is None:
        return None
    try:
        index = extract_icon.load_index()
        match = extract_icon.find(index, query)
    except SystemExit:
        return None
    except Exception:
        return None
    if not match:
        return None
    return match[1].get("style")


def cell(parent: ET.Element, cell_id: str, value: str, style: str, x: int, y: int, w: int, h: int, *, parent_id: str = "1") -> ET.Element:
    elem = ET.SubElement(
        parent,
        "mxCell",
        {
            "id": cell_id,
            "value": value.replace("\n", "<br>"),
            "style": style,
            "vertex": "1",
            "parent": parent_id,
        },
    )
    ET.SubElement(elem, "mxGeometry", {"x": str(snap(x)), "y": str(snap(y)), "width": str(snap(w)), "height": str(snap(h)), "as": "geometry"})
    return elem


def edge(parent: ET.Element, edge_id: str, value: str, source: Box, target: Box, stroke: str = MUTED) -> ET.Element:
    source_cx = source.x + source.w / 2
    source_cy = source.y + source.h / 2
    target_cx = target.x + target.w / 2
    target_cy = target.y + target.h / 2
    dx = target_cx - source_cx
    dy = target_cy - source_cy
    if abs(dx) >= abs(dy):
        if dx >= 0:
            exit_x, exit_y, entry_x, entry_y = 1, 0.5, 0, 0.5
        else:
            exit_x, exit_y, entry_x, entry_y = 0, 0.5, 1, 0.5
    else:
        if dy >= 0:
            exit_x, exit_y, entry_x, entry_y = 0.5, 1, 0.5, 0
        else:
            exit_x, exit_y, entry_x, entry_y = 0.5, 0, 0.5, 1
    style = (
        "edgeStyle=orthogonalEdgeStyle;rounded=0;html=1;endArrow=block;endFill=1;"
        f"strokeColor={stroke};strokeWidth=1.5;labelBackgroundColor=default;"
        "fontFamily=Helvetica;fontSize=11;fontColor=#1D2D3E;"
        f"exitX={exit_x};exitY={exit_y};exitDx=0;exitDy=0;"
        f"entryX={entry_x};entryY={entry_y};entryDx=0;entryDy=0;"
    )
    elem = ET.SubElement(
        parent,
        "mxCell",
        {
            "id": edge_id,
            "value": value,
            "style": style,
            "edge": "1",
            "parent": "1",
            "source": source.id,
            "target": target.id,
        },
    )
    ET.SubElement(elem, "mxGeometry", {"relative": "1", "as": "geometry"})
    return elem


def render(plan: DiagramPlan, out: Path) -> None:
    mxfile = ET.Element("mxfile")
    diagram = ET.SubElement(mxfile, "diagram", {"id": "sap-semantic", "name": plan.title[:80]})
    model = ET.SubElement(
        diagram,
        "mxGraphModel",
        {
            "dx": "1200",
            "dy": "900",
            "grid": "1",
            "gridSize": "10",
            "guides": "1",
            "tooltips": "1",
            "connect": "1",
            "arrows": "1",
            "fold": "1",
            "page": "1",
            "pageScale": "1",
            "pageWidth": str(plan.width),
            "pageHeight": str(plan.height),
            "math": "0",
            "shadow": "0",
        },
    )
    root = ET.SubElement(model, "root")
    ET.SubElement(root, "mxCell", {"id": "0"})
    ET.SubElement(root, "mxCell", {"id": "1", "parent": "0"})

    title_style = (
        "text;html=1;strokeColor=none;fillColor=none;align=left;verticalAlign=middle;"
        f"whiteSpace=wrap;rounded=0;fontFamily=Helvetica;fontSize=22;fontStyle=1;fontColor={BLUE};"
    )
    subtitle_style = (
        "text;html=1;strokeColor=none;fillColor=none;align=left;verticalAlign=middle;"
        "whiteSpace=wrap;rounded=0;fontFamily=Helvetica;fontSize=12;fontColor=#475E75;"
    )
    cell(root, "title", plan.title, title_style, 30, 20, plan.width - 60, 40)
    cell(root, "subtitle", plan.subtitle, subtitle_style, 30, 60, plan.width - 60, 20)

    zone_style = (
        "rounded=1;whiteSpace=wrap;html=1;absoluteArcSize=1;arcSize=16;"
        "strokeWidth=1.5;fontFamily=Helvetica;fontSize=14;fontStyle=1;"
        "align=left;verticalAlign=top;spacing=12;"
    )
    for zone in plan.zones:
        style = f"{zone_style}strokeColor={zone.stroke};fillColor={zone.fill};fontColor={TEXT};"
        cell(root, zone.id, zone.label, style, zone.x, zone.y, zone.w, zone.h)

    def containing_zone(box: Box) -> Box | None:
        for zone in plan.zones:
            if (
                box.x >= zone.x
                and box.y >= zone.y
                and box.x + box.w <= zone.x + zone.w
                and box.y + box.h <= zone.y + zone.h
            ):
                return zone
        return None

    card_style = (
        "rounded=1;whiteSpace=wrap;html=1;absoluteArcSize=1;arcSize=12;"
        "strokeWidth=1.5;fontFamily=Helvetica;fontSize=14;fontStyle=1;"
        "align=center;verticalAlign=middle;spacing=8;"
    )
    icon_style_base = "ellipse;whiteSpace=wrap;html=1;aspect=fixed;strokeColor=#D5DADD;fillColor=#F5F6F7;"
    for box in plan.boxes:
        style = f"{card_style}strokeColor={box.stroke};fillColor={box.fill};fontColor={TEXT};"
        if box.icon is not None:
            style += "spacingLeft=36;"
        zone = containing_zone(box)
        parent_id = zone.id if zone else "1"
        x = box.x - zone.x if zone else box.x
        y = box.y - zone.y if zone else box.y
        cell(root, box.id, box.label, style, x, y, box.w, box.h, parent_id=parent_id)
        icon = icon_style(box.icon)
        if icon:
            icon_id = f"{box.id}-icon"
            icon_cell = ET.SubElement(
                root,
                "mxCell",
                {
                    "id": icon_id,
                    "value": "",
                    "style": icon,
                    "vertex": "1",
                    "parent": box.id,
                },
            )
            ET.SubElement(icon_cell, "mxGeometry", {"x": "10", "y": "20", "width": "30", "height": "30", "as": "geometry"})
        elif box.icon is not None:
            cell(root, f"{box.id}-icon", "", icon_style_base, 10, 20, 30, 30, parent_id=box.id)

    boxes_by_id = {box.id: box for box in plan.boxes}
    for e in plan.edges:
        source = boxes_by_id.get(e.source)
        target = boxes_by_id.get(e.target)
        if source is None or target is None:
            continue
        edge(root, e.id, e.label, source, target, e.stroke)

    pill_style = (
        "rounded=1;whiteSpace=wrap;html=1;absoluteArcSize=1;arcSize=50;"
        "strokeColor=#475E75;fillColor=#FCFCFC;strokeWidth=1;fontFamily=Helvetica;"
        "fontSize=10;fontStyle=1;fontColor=#475E75;align=center;verticalAlign=middle;"
    )
    for pill in plan.pills:
        cell(root, pill.id, pill.label, pill_style, pill.x, pill.y, pill.w, pill.h)

    footer_style = (
        "text;html=1;strokeColor=none;fillColor=none;align=left;verticalAlign=middle;"
        "whiteSpace=wrap;rounded=0;fontFamily=Helvetica;fontSize=11;fontColor=#475E75;"
    )
    cell(root, "footer", "Diagram Level: 2", footer_style, 30, plan.height - 60, 180, 20)

    tree = ET.ElementTree(mxfile)
    ET.indent(tree, space="  ")
    out.parent.mkdir(parents=True, exist_ok=True)
    tree.write(out, encoding="unicode", xml_declaration=False)


def plan_for(description: str, archetype: str | None = None) -> DiagramPlan:
    chosen = archetype or infer_archetype(description)
    planner = PLANNERS.get(chosen)
    if planner is None:
        raise ValueError(f"unknown archetype {chosen!r}; choose one of {', '.join(sorted(PLANNERS))}")
    return planner(description)


def main(argv: Iterable[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("description", nargs="*", help="diagram request; stdin if omitted")
    ap.add_argument("-o", "--out", type=Path, required=True)
    ap.add_argument("--archetype", choices=sorted(PLANNERS), help="override automatic archetype detection")
    ap.add_argument("--json", action="store_true", help="print selected semantic plan summary")
    args = ap.parse_args(list(argv) if argv is not None else None)

    description = " ".join(args.description).strip() or sys.stdin.read().strip()
    if not description:
        print("description required", file=sys.stderr)
        return 2
    plan = plan_for(description, args.archetype)
    render(plan, args.out)
    if args.json:
        print(
            json.dumps(
                {
                    "archetype": plan.archetype,
                    "title": plan.title,
                    "out": str(args.out),
                    "boxes": len(plan.boxes),
                    "edges": len(plan.edges),
                    "pills": len(plan.pills),
                    "zones": len(plan.zones),
                },
                indent=2,
            )
        )
    else:
        print(f"rendered {args.out} using {plan.archetype} archetype")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
