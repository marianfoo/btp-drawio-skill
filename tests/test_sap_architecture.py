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


class SemanticRendererTests(unittest.TestCase):
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
