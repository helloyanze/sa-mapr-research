import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from mapping_normalization import (  # noqa: E402
    canonicalize_claimed_mappings,
    normalize_change_type,
    normalize_file,
    normalize_method_signature,
    normalize_symbol,
    replay_mapping,
)
from revised_verifier import validate_claimed_mapping  # noqa: E402


def contract(method="getObject"):
    return {
        "hard_repair_scope": {"allowed_source_files": ["org/example/KeyedObjects2D.java"]},
        "evidence_anchor": [{"id": "E1", "file": "org/example/KeyedObjects2D.java", "method": method}],
        "repair_obligations": [{"id": "O1", "evidence_anchor_id": "E1"}],
    }


def realized(*methods, symbol=None, change_type=None):
    return [{
        "obligation_id": "O1",
        "actual_patch_targets": [{
            "file": "org/example/KeyedObjects2D.java",
            "method_signature": method,
            "symbol": symbol,
            "change_type": change_type,
        } for method in methods],
        "actual_patch_locations": [f"org/example/KeyedObjects2D.java::{method}" for method in methods],
        "realized": bool(methods),
    }]


def claim(location, **extra):
    return [{"obligation_id": "O1", "patch_location": location, "justification": "fixture", **extra}]


class TestMappingNormalization(unittest.TestCase):
    def assert_consistent(self, claimed, actual, fixture=None):
        fixture = fixture or contract()
        valid, problems = validate_claimed_mapping(fixture, claimed)
        self.assertTrue(valid, problems)
        replay = replay_mapping(fixture, claimed, actual, valid)
        self.assertTrue(replay["metrics"]["mapping_consistent"], replay["comparison"])
        return replay

    def test_method_parameter_spacing_is_equal(self):
        self.assertEqual(
            normalize_method_signature("getObject(Comparable, Comparable)"),
            normalize_method_signature("getObject(Comparable,Comparable)"),
        )
        replay = self.assert_consistent(
            claim("org/example/KeyedObjects2D.java, getObject(Comparable, Comparable) method, line 123"),
            realized("getObject(Comparable,Comparable)"),
        )
        self.assertEqual(replay["metrics"]["mapping_precision"], 1.0)

    def test_class_qualified_method_is_equal(self):
        self.assertEqual(
            normalize_method_signature("KeyedObjects2D::getObject(Comparable,Comparable)"),
            "getObject(Comparable,Comparable)",
        )
        self.assert_consistent(
            claim("org/example/KeyedObjects2D.java::KeyedObjects2D::getObject(Comparable,Comparable)"),
            realized("getObject(Comparable,Comparable)"),
        )

    def test_relative_and_absolute_file_are_equal(self):
        known = ["org/example/KeyedObjects2D.java"]
        self.assertEqual(normalize_file("/tmp/d4j/source/org/example/KeyedObjects2D.java", known), known[0])
        self.assert_consistent(
            claim("/tmp/d4j/source/org/example/KeyedObjects2D.java::getObject(Comparable,Comparable)"),
            realized("getObject(Comparable,Comparable)"),
        )

    def test_windows_and_linux_file_are_equal(self):
        known = ["org/example/KeyedObjects2D.java"]
        self.assertEqual(normalize_file(r"D:\work\source\org\example\KeyedObjects2D.java", known), known[0])
        self.assert_consistent(
            claim(r"D:\work\source\org\example\KeyedObjects2D.java::getObject(Comparable,Comparable)"),
            realized("getObject(Comparable,Comparable)"),
        )

    def test_overloaded_methods_remain_distinct(self):
        fixture = contract("getObject")
        claimed = claim("org/example/KeyedObjects2D.java::getObject(String)")
        valid, _ = validate_claimed_mapping(fixture, claimed)
        replay = replay_mapping(fixture, claimed, realized("getObject(Integer)"), valid)
        self.assertFalse(replay["metrics"]["mapping_consistent"])
        self.assertEqual(replay["metrics"]["mapping_precision"], 0.0)
        ambiguous = claim("org/example/KeyedObjects2D.java, getObject method")
        valid, _ = validate_claimed_mapping(fixture, ambiguous)
        replay = replay_mapping(fixture, ambiguous, realized("getObject(String)", "getObject(Integer)"), valid)
        self.assertFalse(replay["metrics"]["mapping_consistent"])

    def test_optional_symbol_is_normalized_and_only_compared_when_observable(self):
        self.assertEqual(normalize_symbol("KeyedObjects2D.rowKey"), "rowKey")
        replay = self.assert_consistent(
            claim("org/example/KeyedObjects2D.java::getObject(Comparable,Comparable)", symbol="rowKey"),
            realized("getObject(Comparable,Comparable)"),
        )
        self.assertFalse(replay["metrics"]["mapping_exact"])
        claimed = claim("org/example/KeyedObjects2D.java::getObject(Comparable,Comparable)", symbol="rowKey")
        valid, _ = validate_claimed_mapping(contract(), claimed)
        mismatch = replay_mapping(contract(), claimed, realized("getObject(Comparable,Comparable)", symbol="columnKey"), valid)
        self.assertFalse(mismatch["metrics"]["mapping_consistent"])

    def test_line_number_change_is_auxiliary(self):
        first = canonicalize_claimed_mappings(contract(), claim(
            "org/example/KeyedObjects2D.java, getObject(Comparable, Comparable), line 123"
        ))[0]
        second = canonicalize_claimed_mappings(contract(), claim(
            "org/example/KeyedObjects2D.java, getObject(Comparable, Comparable), line 999"
        ))[0]
        self.assertNotEqual(first["auxiliary"], second["auxiliary"])
        self.assertEqual(first["target"], second["target"])
        self.assert_consistent(claim(
            "org/example/KeyedObjects2D.java, getObject(Comparable, Comparable), line 999"
        ), realized("getObject(Comparable,Comparable)"))

    def test_genuinely_different_method_is_rejected(self):
        claimed = claim("org/example/KeyedObjects2D.java::removeObject(Comparable,Comparable)")
        valid, _ = validate_claimed_mapping(contract(), claimed)
        replay = replay_mapping(contract(), claimed, realized("getObject(Comparable,Comparable)"), valid)
        self.assertFalse(replay["metrics"]["mapping_consistent"])
        self.assertIn("different normalized method signature", replay["comparison"]["entries"][0]["mismatch_reasons"])

    def test_genuinely_different_obligation_id_is_rejected(self):
        claimed = [{"obligation_id": "O9", "patch_location": "org/example/KeyedObjects2D.java::getObject()",
                    "justification": "fixture"}]
        valid, problems = validate_claimed_mapping(contract(), claimed)
        self.assertFalse(valid)
        self.assertTrue(any("unknown obligation" in problem for problem in problems))

    def test_malformed_claimed_mapping_is_rejected(self):
        malformed = [{"obligation_id": "O1", "patch_location": "line 123", "justification": "fixture"}]
        valid, problems = validate_claimed_mapping(contract(), malformed)
        self.assertFalse(valid)
        self.assertTrue(any("malformed target file" in problem for problem in problems))

    def test_constructor_array_generic_and_qualified_types(self):
        self.assertEqual(
            normalize_method_signature(
                "org.example.KeyedObjects2D::KeyedObjects2D(java.util.List<java.lang.String> values, String ... names)",
                "KeyedObjects2D",
            ),
            "<init>(List<String>,String[])",
        )
        self.assertEqual(normalize_change_type("MODIFIED"), "modify")
        self.assertEqual(normalize_change_type("deletion"), "remove")


if __name__ == "__main__":
    unittest.main()
