"""
Run the SILD Conformance Test Vectors v2 v0.1 against analyse_hl7_message().

Sibling to test_conformance.py — this file runs the HL7 v2 vector set,
test_conformance.py runs the FHIR R4 vector set.

Usage:
    python -m venv .venv && . .venv/bin/activate
    pip install -r tests/requirements.txt
    pytest tests/ -v

The conformance behaviour requires that for the rule under test, the
detector's output set equals the expected_findings set (other rules may
add additional findings — only the rule-under-test slice is checked).

Path comparison is currently SEGMENT-LEVEL (see conformance_vectors_v2.py).
This is a documented limitation: the detector tracks 'SEG/<id>', vectors
specify 'SEG-<field>'. Closing this gap is open work, mirroring the
FHIR-side strict-path roadmap.
"""
from __future__ import annotations

import pytest

import sild_detector  # noqa: E402 — populated by conftest.py sys.path injection
from tests.conformance_vectors_v2 import (
    Vector,
    detector_findings_for_rule,
    findings_match,
    load_vectors,
)


_VECTORS: list[Vector] = load_vectors()


def _ids(vec: Vector) -> str:
    return f"{vec.test_id} [{vec.category}]"


@pytest.mark.parametrize("vector", _VECTORS, ids=_ids)
def test_conformance_vector_v2(vector: Vector) -> None:
    report = sild_detector.analyse_hl7_message(vector.message)
    actual = detector_findings_for_rule(report, vector.rule)
    ok, why = findings_match(actual, vector.expected_findings)
    assert ok, (
        f"v2-Vector {vector.test_id} ({vector.category}) did not match:\n"
        f"  rule:        {vector.rule}\n"
        f"  description: {vector.description}\n"
        f"  expected:    {vector.expected_findings}\n"
        f"  actual:      {actual}\n"
        f"  reason:      {why}"
    )
