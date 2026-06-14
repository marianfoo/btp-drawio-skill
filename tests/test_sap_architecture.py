from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SKILL_DIR = ROOT / "plugins/sap-architecture/skills/sap-architecture"
SCRIPTS_DIR = SKILL_DIR / "scripts"
REFERENCE_DIR = SKILL_DIR / "assets/reference-examples"

sys.path.insert(0, str(SCRIPTS_DIR))


def load_script(name: str):
    path = SCRIPTS_DIR / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot import {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


compare = load_script("compare")
extract_icon = load_script("extract_icon")
render_semantic = load_script("render_semantic")
scaffold_diagram = load_script("scaffold_diagram")
validate = load_script("validate")


class CompareTests(unittest.TestCase):
    def test_all_reference_self_scores_are_100(self) -> None:
        bad: list[tuple[str, float]] = []
        for path in sorted(REFERENCE_DIR.glob("*.drawio")):
            fp = compare.fingerprint(path)
            score = compare.compare(fp, fp).score
            if score != 100.0:
                bad.append((path.name, score))
        self.assertEqual([], bad)

    def test_scenario_specific_pills_do_not_penalize_self_compare(self) -> None:
        path = REFERENCE_DIR / "ac_RA0027_SIEM_SOAR_ETD.drawio"
        fp = compare.fingerprint(path)
        result = compare.compare(fp, fp)
        self.assertEqual(100.0, result.score)
        self.assertEqual(1.0, result.breakdown["pill_vocab"])


class SelectionTests(unittest.TestCase):
    def test_external_private_link_reference_can_outrank_bundled_template(self) -> None:
        external_roots = [p for p in scaffold_diagram.EXTERNAL_REFERENCE_ROOTS if p.exists()]
        if not external_roots:
            self.skipTest("cached external SAP references are not available")
        query = "Secure connectivity with SAP Private Link service between SAP BTP and hyperscaler services on AWS or Azure"
        internal = scaffold_diagram.rank_candidates(query, 1, include_external=False)[0]
        expanded = scaffold_diagram.rank_candidates(query, 1, include_external=True)[0]
        self.assertEqual("ac_RA0006_PrivateLinkService.drawio", Path(internal.path).name)
        self.assertEqual("Secure-Connectivity-with-SAP-Private-Link-service.drawio", Path(expanded.path).name)


class IconLookupTests(unittest.TestCase):
    def test_backend_system_query_does_not_match_wrong_btp_service_icon(self) -> None:
        index = extract_icon.load_index()
        self.assertTrue(extract_icon.is_backend_system_query("SAP S/4HANA"))
        self.assertIsNone(extract_icon.find(index, "SAP S/4HANA"))

    def test_cloud_connector_still_matches_service_icon(self) -> None:
        index = extract_icon.load_index()
        match = extract_icon.find(index, "Cloud Connector")
        self.assertIsNotNone(match)
        self.assertEqual("cloud-10-connector", match[0])


class ValidateTests(unittest.TestCase):
    def test_edge_validation_uses_absolute_child_geometry_and_allows_pills(self) -> None:
        drawio = """<mxfile>
  <diagram id="test" name="test">
    <mxGraphModel page="1" pageWidth="800" pageHeight="600">
      <root>
        <mxCell id="0"/>
        <mxCell id="1" parent="0"/>
        <mxCell id="z1" value="Zone 1" vertex="1" parent="1"
          style="rounded=1;whiteSpace=wrap;html=1;absoluteArcSize=1;arcSize=16;strokeColor=#0070F2;fillColor=#EBF8FF;fontFamily=Helvetica;fontSize=14;fontColor=#1D2D3E;">
          <mxGeometry x="100" y="100" width="300" height="300" as="geometry"/>
        </mxCell>
        <mxCell id="z2" value="Zone 2" vertex="1" parent="1"
          style="rounded=1;whiteSpace=wrap;html=1;absoluteArcSize=1;arcSize=16;strokeColor=#475E75;fillColor=#F5F6F7;fontFamily=Helvetica;fontSize=14;fontColor=#1D2D3E;">
          <mxGeometry x="500" y="100" width="300" height="300" as="geometry"/>
        </mxCell>
        <mxCell id="a" value="Source" vertex="1" parent="z1"
          style="rounded=1;whiteSpace=wrap;html=1;absoluteArcSize=1;arcSize=12;strokeColor=#0070F2;fillColor=#FFFFFF;strokeWidth=1.5;fontFamily=Helvetica;fontSize=14;fontColor=#1D2D3E;">
          <mxGeometry x="20" y="20" width="80" height="40" as="geometry"/>
        </mxCell>
        <mxCell id="b" value="Target" vertex="1" parent="z1"
          style="rounded=1;whiteSpace=wrap;html=1;absoluteArcSize=1;arcSize=12;strokeColor=#0070F2;fillColor=#FFFFFF;strokeWidth=1.5;fontFamily=Helvetica;fontSize=14;fontColor=#1D2D3E;">
          <mxGeometry x="20" y="220" width="80" height="40" as="geometry"/>
        </mxCell>
        <mxCell id="p" value="HTTPS" vertex="1" parent="z1"
          style="rounded=1;whiteSpace=wrap;html=1;absoluteArcSize=1;arcSize=50;strokeColor=#475E75;fillColor=#FCFCFC;strokeWidth=1;fontFamily=Helvetica;fontSize=10;fontColor=#475E75;">
          <mxGeometry x="20" y="120" width="80" height="20" as="geometry"/>
        </mxCell>
        <mxCell id="c" value="Obstacle in other zone" vertex="1" parent="z2"
          style="rounded=1;whiteSpace=wrap;html=1;absoluteArcSize=1;arcSize=12;strokeColor=#0070F2;fillColor=#FFFFFF;strokeWidth=1.5;fontFamily=Helvetica;fontSize=14;fontColor=#1D2D3E;">
          <mxGeometry x="20" y="100" width="100" height="100" as="geometry"/>
        </mxCell>
        <mxCell id="e1" value="" edge="1" parent="1" source="a" target="b"
          style="edgeStyle=orthogonalEdgeStyle;rounded=0;html=1;endArrow=block;endFill=1;strokeColor=#475E75;strokeWidth=1.5;fontFamily=Helvetica;fontSize=11;fontColor=#1D2D3E;">
          <mxGeometry relative="1" as="geometry"/>
        </mxCell>
      </root>
    </mxGraphModel>
  </diagram>
</mxfile>"""
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "parented.drawio"
            path.write_text(drawio, encoding="utf-8")
            report = validate.validate(path)

        self.assertEqual([], report.errors)
        through_warnings = [i for i in report.warnings if "passes through cell" in i.msg]
        self.assertEqual([], through_warnings)

    def test_orphaned_edge_is_structural_warning(self) -> None:
        drawio = """<mxfile>
  <diagram id="test" name="test">
    <mxGraphModel page="1" pageWidth="800" pageHeight="600">
      <root>
        <mxCell id="0"/>
        <mxCell id="1" parent="0"/>
        <mxCell id="a" value="Source" vertex="1" parent="1"
          style="rounded=1;whiteSpace=wrap;html=1;absoluteArcSize=1;arcSize=12;strokeColor=#0070F2;fillColor=#FFFFFF;strokeWidth=1.5;fontFamily=Helvetica;fontSize=14;fontColor=#1D2D3E;">
          <mxGeometry x="100" y="100" width="100" height="60" as="geometry"/>
        </mxCell>
        <mxCell id="e1" value="" edge="1" parent="1" source="a" target="missing"
          style="edgeStyle=orthogonalEdgeStyle;rounded=0;html=1;endArrow=block;endFill=1;strokeColor=#475E75;strokeWidth=1.5;fontFamily=Helvetica;fontSize=11;fontColor=#1D2D3E;">
          <mxGeometry relative="1" as="geometry"/>
        </mxCell>
      </root>
    </mxGraphModel>
  </diagram>
</mxfile>"""
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "orphaned.drawio"
            path.write_text(drawio, encoding="utf-8")
            report = validate.validate(path)

        self.assertEqual([], report.errors)
        self.assertTrue(any("missing target id 'missing'" in i.msg for i in report.warnings))


class SemanticRendererTests(unittest.TestCase):
    def test_cloud_connector_request_uses_on_prem_connectivity_archetype(self) -> None:
        description = (
            "Developer consumes SAP S/4HANA On-Premise from VS Code through ARC-1 "
            "running on SAP BTP Cloud Foundry with Destination service, Connectivity "
            "service, and SAP Cloud Connector"
        )
        plan = render_semantic.plan_for(description)
        self.assertEqual("on-prem-connectivity", plan.archetype)
        self.assertIn("SAP Cloud\nConnector", {box.label for box in plan.boxes})

        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "on-prem.drawio"
            render_semantic.render(plan, out)
            report = validate.validate(out)
            self.assertEqual([], report.errors)

    def test_cap_hana_fiori_request_uses_btp_application_not_integration_flow(self) -> None:
        plan = render_semantic.plan_for("CAP application with SAP HANA Cloud and SAP Fiori frontend")
        self.assertEqual("btp-application", plan.archetype)
        self.assertIn("SAP HANA Cloud", {box.label for box in plan.boxes})

    def test_security_operations_renderer_validates_and_improves_template_ceiling(self) -> None:
        description = (
            "SIEM and SOAR with SAP Enterprise Threat Detection, FortiSIEM, "
            "FortiSOAR, ITSM ticketing, notification system, SAP S/4HANA "
            "on-premise and cloud enterprise resources"
        )
        target = REFERENCE_DIR / "ac_RA0027_SIEM_SOAR_ETD.drawio"
        weak_template = REFERENCE_DIR / "ac_RA0014_OData_CAP_PrivateLink.drawio"
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "semantic-siem.drawio"
            render_semantic.render(render_semantic.plan_for(description), out)
            report = validate.validate(out)
            self.assertEqual([], report.errors)
            semantic_score = compare.compare(compare.fingerprint(target), compare.fingerprint(out)).score
            weak_score = compare.compare(compare.fingerprint(target), compare.fingerprint(weak_template)).score
            self.assertGreaterEqual(semantic_score, weak_score + 7.0)


if __name__ == "__main__":
    unittest.main()
