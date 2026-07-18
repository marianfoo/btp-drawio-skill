from __future__ import annotations

import importlib.util
import hashlib
import json
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
from statistics import median
from pathlib import Path
import datetime as dt


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
autofix = load_script("autofix")
extract_icon = load_script("extract_icon")
render_semantic = load_script("render_semantic")
relabel = load_script("relabel")
scaffold_diagram = load_script("scaffold_diagram")
validate = load_script("validate")
validate_semantics = load_script("validate_semantics")
provenance = load_script("provenance")
verify_delivery = load_script("verify_delivery")
check_currentness = load_script("check_currentness")
build_sequence_draft = load_script("build_sequence_draft")
build_csv_variation = load_script("build_csv_variation")
scaffold_identity_pack = load_script("scaffold_identity_pack")
export_pack = load_script("export_pack")


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

    def test_derivative_footer_is_excluded_from_template_fingerprint(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "source.drawio"
            derivative = Path(tmp) / "derivative.drawio"
            source.write_text("""<mxfile><diagram><mxGraphModel pageWidth="800" pageHeight="600">
              <root><mxCell id="0"/><mxCell id="1" parent="0"/>
              <mxCell id="content" value="Architecture Content" vertex="1" parent="1"
                style="text;html=1;fontFamily=Helvetica;"><mxGeometry x="20" y="20" width="200" height="40" as="geometry"/></mxCell>
              </root></mxGraphModel></diagram></mxfile>""", encoding="utf-8")
            provenance.sanitize_file(
                source,
                derivative,
                source_template="template.drawio",
                source_url="https://example.invalid/template",
            )
            source_fp = compare.fingerprint(source)
            derivative_fp = compare.fingerprint(derivative)
        self.assertEqual(source_fp.canvas_h, derivative_fp.canvas_h)
        self.assertEqual(source_fp.label_tokens, derivative_fp.label_tokens)
        self.assertEqual(source_fp.cells_total, derivative_fp.cells_total)

    def test_sap_likeness_scores_semantic_output_without_template_similarity(self) -> None:
        description = (
            "Developer consumes SAP S/4HANA On-Premise from VS Code through ARC-1 "
            "running on SAP BTP Cloud Foundry with Destination service, Connectivity "
            "service, and SAP Cloud Connector"
        )
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "on-prem.drawio"
            render_semantic.render(render_semantic.plan_for(description), out)
            report = validate.validate(out)
            quality = compare.sap_likeness(compare.fingerprint(out), validator_errors=len(report.errors))
        self.assertGreaterEqual(quality.score, 90.0)

    def test_sap_likeness_scores_real_sap_agentic_reference_above_gate(self) -> None:
        path = REFERENCE_DIR / "ac_RA0029_AgenticAI_root.drawio"
        quality = compare.sap_likeness(compare.fingerprint(path))
        self.assertGreaterEqual(quality.score, 90.0)

    def test_sap_likeness_reference_corpus_median_is_above_gate(self) -> None:
        scores = [
            compare.sap_likeness(compare.fingerprint(path)).score
            for path in sorted(REFERENCE_DIR.glob("*.drawio"))
        ]
        self.assertEqual(71, len(scores))
        self.assertGreaterEqual(median(scores), 90.0)

    def test_fingerprint_scopes_multipage_files_to_first_page(self) -> None:
        drawio = """<mxfile>
  <diagram id="page-1" name="First">
    <mxGraphModel page="1" pageWidth="100" pageHeight="100">
      <root>
        <mxCell id="0"/>
        <mxCell id="1" parent="0"/>
      </root>
    </mxGraphModel>
  </diagram>
  <diagram id="page-2" name="Second">
    <mxGraphModel page="1" pageWidth="2000" pageHeight="1200">
      <root>
        <mxCell id="0"/>
        <mxCell id="1" parent="0"/>
        <mxCell id="z1" value="Zone" vertex="1" parent="1"
          style="rounded=1;whiteSpace=wrap;html=1;absoluteArcSize=1;arcSize=16;strokeColor=#0070F2;fillColor=#EBF8FF;strokeWidth=1.5;fontFamily=Helvetica;">
          <mxGeometry x="100" y="100" width="500" height="300" as="geometry"/>
        </mxCell>
      </root>
    </mxGraphModel>
  </diagram>
</mxfile>"""
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "multi.drawio"
            path.write_text(drawio, encoding="utf-8")
            fp = compare.fingerprint(path)
        self.assertEqual((100, 100), (fp.canvas_w, fp.canvas_h))
        self.assertEqual(2, fp.cells_total)
        self.assertEqual(0, fp.zones)

    def test_sap_likeness_rejects_dark_unstructured_diagram(self) -> None:
        drawio = """<mxfile>
  <diagram id="test" name="test">
    <mxGraphModel page="1" pageWidth="800" pageHeight="600" pageBackgroundColor="#123456">
      <root>
        <mxCell id="0"/>
        <mxCell id="1" parent="0"/>
        <mxCell id="a" value="Prompt" vertex="1" parent="1"
          style="rounded=1;whiteSpace=wrap;html=1;arcSize=50;strokeColor=#FF00FF;fillColor=#000000;fontFamily=Comic Sans MS;">
          <mxGeometry x="13" y="17" width="123" height="31" as="geometry"/>
        </mxCell>
      </root>
    </mxGraphModel>
  </diagram>
</mxfile>"""
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bad.drawio"
            path.write_text(drawio, encoding="utf-8")
            report = validate.validate(path)
            quality = compare.sap_likeness(compare.fingerprint(path), validator_errors=len(report.errors))
        self.assertLess(quality.score, 70.0)


class AutofixTests(unittest.TestCase):
    def test_apply_all_repairs_common_mechanical_issues_and_is_idempotent(self) -> None:
        raw = """<mxfile><!-- remove me -->
  <diagram id="test" name="test">
    <mxGraphModel page="1" pageWidth="801" pageHeight="599">
      <root>
        <mxCell id="0"/>
        <mxCell id="1" parent="0"/>
        <mxCell id="a" value="Card" vertex="1" parent="1"
          style="rounded=1;whiteSpace=wrap;html=1;arcSize=12;strokeColor=#0070f2;fillColor=#ffffff;strokeWidth=1.2;fontFamily=Arial;">
          <mxGeometry x="13" y="27" width="101" height="59" as="geometry"/>
        </mxCell>
      </root>
    </mxGraphModel>
  </diagram>
</mxfile>"""
        fixed, stats = autofix.apply_all(raw)
        fixed_again, stats_again = autofix.apply_all(fixed)
        self.assertGreater(sum(stats.values()), 0)
        self.assertEqual(fixed, fixed_again)
        self.assertEqual(0, sum(stats_again.values()))
        self.assertNotIn("<!--", fixed)
        self.assertIn("absoluteArcSize=1", fixed)
        self.assertIn("strokeColor=#0070F2", fixed)
        self.assertIn("strokeWidth=1", fixed)
        self.assertIn("fontFamily=Helvetica", fixed)

    def test_grid_disabled_preserves_official_template_geometry(self) -> None:
        raw = """<mxfile><diagram><mxGraphModel grid="0"><root>
          <mxCell id="0"/><mxCell id="1" parent="0"/>
          <mxCell id="a" vertex="1" parent="1"><mxGeometry x="13.25" y="27.5" width="101.5" height="59.25" as="geometry"/></mxCell>
        </root></mxGraphModel></diagram></mxfile>"""
        fixed, stats = autofix.apply_all(raw)
        self.assertIn('x="13.25"', fixed)
        self.assertIn('height="59.25"', fixed)
        self.assertEqual(0, stats["geometry"])


class SelectionTests(unittest.TestCase):
    def test_authentication_request_ignores_exclusion_terms_when_ranking(self) -> None:
        query = (
            "Create an L2 SAP authentication architecture for a business user accessing an SAP BTP "
            "application through SAP Cloud Identity Services - Identity Authentication, federated "
            "with a corporate identity provider using SAML 2.0 or OIDC. Authentication only: "
            "exclude Identity Provisioning, SCIM, and identity lifecycle."
        )
        ranked = scaffold_diagram.rank_candidates(query, 5)
        self.assertEqual(
            "btp_SAP_Cloud_Identity_Services_Authentication_L2.drawio",
            Path(ranked[0].path).name,
        )
        self.assertNotIn(
            "ac_RA0029_AgenticAI_root.drawio",
            [Path(candidate.path).name for candidate in ranked[:3]],
        )

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

    def test_build_work_zone_ambiguous_query_prefers_standard_edition(self) -> None:
        index = extract_icon.load_index()
        match = extract_icon.find(index, "Build Work Zone")
        self.assertIsNotNone(match)
        self.assertEqual("sap-build-work-zone-10-standard-edition", match[0])

    def test_datasphere_icon_is_available_for_semantic_renderer(self) -> None:
        self.assertIsNotNone(render_semantic.icon_style("sap datasphere"))


class RelabelTests(unittest.TestCase):
    def test_relabel_by_id_and_visible_label_preserves_simple_wrapper(self) -> None:
        drawio = """<mxfile>
  <diagram id="test" name="test">
    <mxGraphModel page="1" pageWidth="800" pageHeight="600">
      <root>
        <mxCell id="0"/>
        <mxCell id="1" parent="0"/>
        <mxCell id="zone-title" value="&lt;b&gt;Old&lt;br&gt;Zone&lt;/b&gt;" vertex="1" parent="1"
          style="text;html=1;fontFamily=Helvetica;">
          <mxGeometry x="20" y="20" width="120" height="40" as="geometry"/>
        </mxCell>
        <mxCell id="plain" value="Plain Label" vertex="1" parent="1"
          style="text;html=1;fontFamily=Helvetica;">
          <mxGeometry x="20" y="80" width="120" height="40" as="geometry"/>
        </mxCell>
      </root>
    </mxGraphModel>
  </diagram>
</mxfile>"""
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "in.drawio"
            mapping = Path(tmp) / "labels.json"
            out = Path(tmp) / "out.drawio"
            src.write_text(drawio, encoding="utf-8")
            mapping.write_text(
                json.dumps(
                    {
                        "ids": {"zone-title": "New\nZone"},
                        "labels": {"Plain Label": "Renamed Label"},
                    }
                ),
                encoding="utf-8",
            )
            replacements = relabel.relabel_file(src, mapping, out)
            cells = {cell.get("id"): cell for cell in ET.parse(out).getroot().iter("mxCell")}

        self.assertEqual(2, len(replacements))
        self.assertEqual("<b>New<br>Zone</b>", cells["zone-title"].get("value"))
        self.assertEqual("Renamed Label", cells["plain"].get("value"))


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

    def test_event_mesh_phrase_routes_to_integration_flow(self) -> None:
        plan = render_semantic.plan_for("Event Mesh integration from SAP S/4HANA to a Kafka consumer")
        self.assertEqual("integration-flow", plan.archetype)

    def test_hyperscaler_data_integration_routes_to_data_integration(self) -> None:
        plan = render_semantic.plan_for("Hyperscaler data integration from SAP S/4HANA to Databricks")
        self.assertEqual("data-integration", plan.archetype)

    def test_semantic_renderer_adds_l2_legend(self) -> None:
        plan = render_semantic.plan_for("CAP application with SAP HANA Cloud and SAP Fiori frontend")
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "app.drawio"
            render_semantic.render(plan, out)
            labels = {
                compare.clean_label(cell.get("value") or "")
                for cell in ET.parse(out).getroot().iter("mxCell")
            }
            report = validate.validate(out)
        self.assertIn("Legend", labels)
        self.assertEqual([], report.errors)

    def test_ai_agent_uses_joule_as_separate_purple_zone(self) -> None:
        plan = render_semantic.plan_for("AI agent with SAP Joule, MCP, and SAP S/4HANA")
        zone_by_id = {zone.id: zone for zone in plan.zones}
        self.assertIn("z-joule", zone_by_id)
        self.assertEqual("#5D36FF", zone_by_id["z-joule"].stroke)
        self.assertEqual("#F1ECFF", zone_by_id["z-joule"].fill)

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


class GuardedSemanticTests(unittest.TestCase):
    SIMPLE_DIAGRAM = """<mxfile>
  <diagram id="test" name="test">
    <mxGraphModel page="1" pageWidth="800" pageHeight="600">
      <root>
        <mxCell id="0"/>
        <mxCell id="1" parent="0"/>
        <mxCell id="zone" value="SAP BTP" vertex="1" parent="1"
          style="rounded=1;whiteSpace=wrap;html=1;absoluteArcSize=1;arcSize=16;strokeColor=#0070F2;fillColor=#EBF8FF;fontFamily=Helvetica;">
          <mxGeometry x="40" y="80" width="700" height="420" as="geometry"/>
        </mxCell>
        <mxCell id="app" value="CAP Application" vertex="1" parent="zone"
          style="rounded=1;whiteSpace=wrap;html=1;absoluteArcSize=1;arcSize=12;strokeColor=#0070F2;fillColor=#FFFFFF;fontFamily=Helvetica;">
          <mxGeometry x="60" y="120" width="180" height="60" as="geometry"/>
        </mxCell>
        <mxCell id="dest" value="SAP Destination service" vertex="1" parent="zone"
          style="rounded=1;whiteSpace=wrap;html=1;absoluteArcSize=1;arcSize=12;strokeColor=#0070F2;fillColor=#FFFFFF;fontFamily=Helvetica;">
          <mxGeometry x="360" y="120" width="200" height="60" as="geometry"/>
        </mxCell>
        <mxCell id="protocol" value="OData/REST" vertex="1" parent="1"
          style="rounded=1;whiteSpace=wrap;html=1;absoluteArcSize=1;arcSize=50;strokeColor=#475E75;fillColor=#FCFCFC;fontFamily=Helvetica;">
          <mxGeometry x="310" y="210" width="100" height="20" as="geometry"/>
        </mxCell>
        <mxCell id="flow" edge="1" parent="1" source="app" target="dest"
          style="edgeStyle=orthogonalEdgeStyle;rounded=0;html=1;endArrow=block;strokeColor=#475E75;fontFamily=Helvetica;">
          <mxGeometry relative="1" as="geometry"/>
        </mxCell>
      </root>
    </mxGraphModel>
  </diagram>
</mxfile>"""

    def write_case(self, tmp: str, *, reverse: bool = False) -> tuple[Path, Path]:
        drawio = Path(tmp) / "case.drawio"
        spec = Path(tmp) / "case.spec.json"
        text = self.SIMPLE_DIAGRAM
        if reverse:
            text = text.replace('source="app" target="dest"', 'source="dest" target="app"')
        drawio.write_text(text, encoding="utf-8")
        spec.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "subject": "CAP application through Destination",
                    "level": "L2",
                    "required_zones": ["SAP BTP"],
                    "required_nodes": [
                        {"name": "CAP application", "aliases": ["CAP Application"]},
                        "SAP Destination service",
                    ],
                    "required_flows": [
                        {"from": "CAP application", "to": "SAP Destination service"}
                    ],
                    "required_terms": ["OData/REST"],
                    "forbidden_terms": ["Direct public internet access"],
                    "provenance": {"allowed_raster_hashes": []},
                }
            ),
            encoding="utf-8",
        )
        return drawio, spec

    def test_semantic_contract_passes_required_content_and_direction(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            drawio, spec = self.write_case(tmp)
            report = validate_semantics.validate_semantics(drawio, spec)
        self.assertEqual([], report.errors)
        self.assertEqual(1, len(report.matched["required_flows"]))

    def test_semantic_contract_rejects_reversed_flow(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            drawio, spec = self.write_case(tmp, reverse=True)
            report = validate_semantics.validate_semantics(drawio, spec)
        self.assertTrue(any(issue.code == "missing-flow" for issue in report.errors))

    def test_semantic_endpoint_annotations_preserve_pill_based_rendering(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            drawio, spec = self.write_case(tmp)
            text = drawio.read_text(encoding="utf-8").replace(
                'source="app" target="dest"',
                'source="protocol" target="protocol" data-semantic-source="app" data-semantic-target="dest"',
            )
            drawio.write_text(text, encoding="utf-8")
            report = validate_semantics.validate_semantics(drawio, spec)
        self.assertEqual([], report.errors)
        self.assertEqual(1, len(report.matched["required_flows"]))

    def test_sap_looking_reference_fails_when_request_component_is_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            spec = Path(tmp) / "wrong.spec.json"
            spec.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "subject": "Cloud Connector requirement",
                        "level": "L2",
                        "required_nodes": ["Impossible Bespoke Control Plane"],
                        "required_zones": [],
                        "required_flows": [],
                        "required_terms": [],
                        "forbidden_terms": [],
                        "provenance": {"allowed_raster_hashes": []},
                    }
                ),
                encoding="utf-8",
            )
            report = validate_semantics.validate_semantics(
                REFERENCE_DIR / "ac_RA0029_AgenticAI_root.drawio", spec
            )
        self.assertTrue(any(issue.code == "missing-required_nodes" for issue in report.errors))

    def test_multipage_claim_controls_reject_unproven_client_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            drawio, _ = self.write_case(tmp)
            root = ET.parse(drawio).getroot()
            first = root.find("diagram")
            self.assertIsNotNone(first)
            first.set("name", "Architecture")
            root.append(ET.fromstring(ET.tostring(first, encoding="unicode")))
            root.findall("diagram")[1].set("name", "Provisioning")
            ET.ElementTree(root).write(drawio, encoding="unicode")
            spec = Path(tmp) / "pack.spec.json"
            page_contract = {
                "level": "L2",
                "required_zones": ["SAP BTP"],
                "required_nodes": ["CAP Application", "SAP Destination service"],
                "required_flows": [{"from": "CAP Application", "to": "SAP Destination service"}],
                "required_terms": ["OData/REST"],
                "forbidden_terms": [],
            }
            spec.write_text(
                json.dumps(
                    {
                        "schema_version": 2,
                        "subject": "Controlled pack",
                        "status": "internal-draft",
                        "claims": [
                            {
                                "id": "client-route",
                                "state": "configured-client-state",
                                "text": "This route is configured.",
                            }
                        ],
                        "pages": [
                            {"name": "Architecture", **page_contract},
                            {"name": "Provisioning", **page_contract},
                        ],
                    }
                ),
                encoding="utf-8",
            )
            report = validate_semantics.validate_semantics(drawio, spec)
        self.assertTrue(any(issue.code == "unproven-client-state" for issue in report.errors))


class ProvenanceTests(unittest.TestCase):
    SOURCE_DIAGRAM = """<mxfile>
  <diagram id="test" name="test">
    <mxGraphModel page="1" pageWidth="800" pageHeight="600">
      <root>
        <mxCell id="0"/>
        <mxCell id="1" parent="0"/>
        <mxCell id="ref" value="Official RA0029" vertex="1" parent="1"
          style="text;html=1;fontFamily=Helvetica;">
          <mxGeometry x="20" y="20" width="100" height="20" as="geometry"/>
        </mxCell>
        <mxCell id="qr" value="QR" vertex="1" parent="1"
          data-provenance-role="official-qr"
          style="shape=image;image=data:image/png,AAAA;">
          <mxGeometry x="700" y="500" width="60" height="60" as="geometry"/>
        </mxCell>
      </root>
    </mxGraphModel>
  </diagram>
</mxfile>"""

    def test_sanitizer_removes_reference_identifiers_and_marks_derivative(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "source.drawio"
            output = Path(tmp) / "output.drawio"
            source.write_text(self.SOURCE_DIAGRAM, encoding="utf-8")
            removed = provenance.sanitize_file(
                source,
                output,
                source_template="ac_RA0029_AgenticAI_root.drawio",
                source_url="https://github.com/SAP/architecture-center",
            )
            root = ET.parse(output).getroot()
            report = provenance.audit_tree(root)
            ref_cell = next(cell for cell in root.iter("mxCell") if cell.get("id") == "ref")
        self.assertIn("qr", removed)
        self.assertEqual("true", root.get("data-guarded-derivative"))
        self.assertEqual([], report.errors)
        self.assertEqual("Official ", ref_cell.get("value"))

    def test_unreviewed_square_raster_is_blocking_in_strict_workflow(self) -> None:
        root = ET.fromstring(self.SOURCE_DIAGRAM.replace('value="QR"', 'value=""').replace(' data-provenance-role="official-qr"', ''))
        provenance.sanitize_tree(
            root,
            source_template="template.drawio",
            source_url="https://example.invalid/template",
        )
        report = provenance.audit_tree(root)
        self.assertEqual(1, len(report.warnings))
        digest = report.candidate_raster_hashes[0]
        allowed = provenance.audit_tree(root, allowed_raster_hashes={digest})
        self.assertEqual([], allowed.warnings)

    def test_repeated_sanitization_does_not_grow_canvas(self) -> None:
        root = ET.fromstring(self.SOURCE_DIAGRAM)
        provenance.sanitize_tree(root, source_template="template.drawio", source_url="https://example.invalid/template")
        first_height = root.find(".//mxGraphModel").get("pageHeight")
        provenance.sanitize_tree(root, source_template="template.drawio", source_url="https://example.invalid/template")
        second_height = root.find(".//mxGraphModel").get("pageHeight")
        self.assertEqual(first_height, second_height)

    def test_sanitizer_places_disclaimer_on_custom_negative_coordinate_layer(self) -> None:
        root = ET.fromstring("""<mxfile>
  <diagram id="test" name="test">
    <mxGraphModel page="1" pageWidth="800" pageHeight="600">
      <root>
        <mxCell id="custom-root"/>
        <mxCell id="custom-layer" parent="custom-root"/>
        <mxCell id="content" value="Architecture" vertex="1" parent="custom-layer">
          <mxGeometry x="-1600" y="-1200" width="760" height="560" as="geometry"/>
        </mxCell>
      </root>
    </mxGraphModel>
  </diagram>
</mxfile>""")
        provenance.sanitize_tree(
            root,
            source_template="template.drawio",
            source_url="https://example.invalid/template",
        )
        disclaimer = next(cell for cell in root.iter("mxCell") if cell.get("id") == "guarded-provenance")
        geometry = disclaimer.find("mxGeometry")
        self.assertEqual("custom-layer", disclaimer.get("parent"))
        self.assertIsNotNone(geometry)
        self.assertLess(float(geometry.get("x") or 0), 0)
        self.assertLess(float(geometry.get("y") or 0), 0)

    def test_multipage_sanitizer_marks_and_audits_every_page_idempotently(self) -> None:
        root = ET.fromstring(self.SOURCE_DIAGRAM)
        second = ET.fromstring(ET.tostring(root.find("diagram"), encoding="unicode"))
        second.set("id", "second")
        second.set("name", "second")
        root.append(second)
        provenance.sanitize_tree(
            root,
            source_template="template.drawio",
            source_url="https://example.invalid/template",
        )
        heights = [diagram.find("mxGraphModel").get("pageHeight") for diagram in root.findall("diagram")]
        provenance.sanitize_tree(
            root,
            source_template="template.drawio",
            source_url="https://example.invalid/template",
        )
        disclaimers = [
            [cell for cell in diagram.iter("mxCell") if cell.get("id") == "guarded-provenance"]
            for diagram in root.findall("diagram")
        ]
        self.assertEqual([1, 1], [len(items) for items in disclaimers])
        self.assertEqual(heights, [diagram.find("mxGraphModel").get("pageHeight") for diagram in root.findall("diagram")])
        self.assertEqual([], provenance.audit_tree(root).errors)


class IdentityPackTests(unittest.TestCase):
    def test_default_pattern_scaffolds_three_guarded_semantic_pages(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "identity.drawio"
            spec = out.with_suffix(".spec.json")
            targets = out.with_suffix(".targets.json")
            scaffold_identity_pack.compose(
                scaffold_identity_pack.load_pattern(scaffold_identity_pack.DEFAULT_PATTERN),
                [],
                output=out,
                spec_output=spec,
                targets_output=targets,
            )
            root = ET.parse(out).getroot()
            report = validate_semantics.validate_semantics(out, spec)
            audit = provenance.audit_tree(root)
            target_data = json.loads(targets.read_text(encoding="utf-8"))
        self.assertEqual(
            ["00--Identity-Landscape", "01--IAS-Proxy-and-BTP-Trust", "02--IPS-Provisioning"],
            [diagram.get("name") for diagram in root.findall("diagram")],
        )
        self.assertTrue(all(diagram.get("data-guarded-source-template") for diagram in root.findall("diagram")))
        self.assertEqual([], report.errors)
        self.assertEqual([], audit.errors)
        self.assertEqual(3, len(target_data["pages"]))

    def test_currentness_flags_stale_release_and_passes_current_control(self) -> None:
        control = json.loads((SKILL_DIR / "assets/currentness.json").read_text(encoding="utf-8"))
        current = check_currentness.check(control, as_of=dt.date(2026, 7, 18), live=False)
        stale = check_currentness.check(control, as_of=dt.date(2027, 1, 1), live=False)
        self.assertTrue(current["ok"])
        self.assertFalse(stale["ok"])
        self.assertTrue(any("stale" in item["status"] for item in stale["upstreams"]))

    def test_sequence_draft_enforces_claim_state_boundaries(self) -> None:
        payload = {
            "schema_version": 1,
            "status": "draft",
            "participants": [{"id": "user", "label": "User"}, {"id": "ias", "label": "IAS"}],
            "messages": [
                {
                    "from": "user",
                    "to": "ias",
                    "label": "Authenticate",
                    "protocol": "OIDC",
                    "state": "proposed-design",
                    "decision_status": "client-confirm",
                }
            ],
        }
        output = build_sequence_draft.build(payload)
        self.assertIn("sequenceDiagram", output)
        self.assertIn("user->>ias: OIDC: Authenticate", output)
        del payload["messages"][0]["decision_status"]
        with self.assertRaisesRegex(ValueError, "requires decision_status"):
            build_sequence_draft.build(payload)

    def test_csv_variation_enforces_client_evidence_and_emits_drawio_directives(self) -> None:
        rows = [
            {
                "id": "ias",
                "label": "Identity Authentication",
                "connect_to": "",
                "protocol": "OIDC",
                "claim_state": "configured-client-state",
                "evidence": "tenant-export-2026-07-18",
            },
            {
                "id": "app",
                "label": "SAP BTP Application",
                "connect_to": "ias",
                "protocol": "OIDC",
                "claim_state": "proposed-design",
                "decision_status": "client-confirm",
            },
        ]
        output = build_csv_variation.build(rows)
        self.assertIn('"invert":true', output)
        self.assertIn('"label":"protocol"', output)
        self.assertIn("Identity Authentication", output)
        rows[0]["evidence"] = ""
        with self.assertRaisesRegex(ValueError, "requires a client evidence reference"):
            build_csv_variation.build(rows)

    def test_page_export_spec_preserves_semantic_contract(self) -> None:
        pack = scaffold_identity_pack.load_pattern(scaffold_identity_pack.DEFAULT_PATTERN)
        spec = {"pages": pack["pages"], "provenance": {"allowed_raster_hashes": []}}
        page = export_pack.page_spec(spec, "01--IAS-Proxy-and-BTP-Trust")
        self.assertEqual(1, page["schema_version"])
        self.assertIn("Identity Authentication", page["required_nodes"])


class GuardedReviewTests(unittest.TestCase):
    def test_grid_snap_warning_signature_ignores_dynamic_counts(self) -> None:
        target = validate.Issue("warning", "align", "grid-snap rate 31.3% below recommended 95% (239/348 values)")
        candidate = validate.Issue("warning", "align", "grid-snap rate 29.4% below recommended 95% (209/296 values)")
        self.assertEqual(verify_delivery.issue_signature(target), verify_delivery.issue_signature(candidate))

    def test_visual_review_is_hash_bound(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            candidate = Path(tmp) / "candidate.png"
            reference = Path(tmp) / "reference.png"
            review = Path(tmp) / "review.json"
            candidate.write_bytes(b"candidate")
            reference.write_bytes(b"reference")
            checks = {
                "nonblank": True,
                "legible": True,
                "no_incoherent_overlap": True,
                "flows_traceable": True,
                "provenance_visible": True,
                "sap_style_consistent": True,
            }
            review.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "reviewer": "Codex",
                        "verdict": "pass",
                        "notes": "Both images inspected at full resolution.",
                        "candidate_sha256": hashlib.sha256(b"candidate").hexdigest(),
                        "reference_sha256": hashlib.sha256(b"reference").hexdigest(),
                        "checks": checks,
                    }
                ),
                encoding="utf-8",
            )
            self.assertEqual([], verify_delivery.load_visual_review(review, candidate, reference))
            incomplete = json.loads(review.read_text(encoding="utf-8"))
            incomplete["checks"] = {"nonblank": True}
            review.write_text(json.dumps(incomplete), encoding="utf-8")
            incomplete_errors = verify_delivery.load_visual_review(review, candidate, reference)
            self.assertTrue(any("checks are incomplete" in error for error in incomplete_errors))
            candidate.write_bytes(b"changed")
            errors = verify_delivery.load_visual_review(review, candidate, reference)
        self.assertTrue(any("changed after visual review" in error for error in errors))


class SourceManifestTests(unittest.TestCase):
    def test_source_manifest_covers_all_bundled_templates_with_current_hashes(self) -> None:
        manifest_path = SKILL_DIR / "assets" / "source-manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        self.assertEqual(71, manifest["reference_count"])
        self.assertEqual(
            {
                "SAP/architecture-center": 52,
                "SAP/btp-solution-diagrams": 11,
                "SAP/sap-btp-reference-architectures": 8,
            },
            manifest["reference_counts_by_source"],
        )
        for item in manifest["references"]:
            path = REFERENCE_DIR / item["file"]
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), item["sha256"])


if __name__ == "__main__":
    unittest.main()
