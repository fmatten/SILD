"""
Run the SILD Conformance Test Vectors v0.1 against analyse_fhir_bundle().

Usage:
    python -m venv .venv && . .venv/bin/activate
    pip install -r tests/requirements.txt
    pytest tests/ -v

The conformance behaviour requires that for the rule under test, the
detector's output set equals the expected_findings set (other rules may
add additional findings — only the rule-under-test slice is checked).

Path comparison is currently RESOURCE-LEVEL (see conformance_vectors.py).
This is a documented limitation: the detector tracks 'ResourceType/id',
vectors specify 'ResourceType.field'. Closing this gap is open work.
"""
from __future__ import annotations

import pytest

import sild_detector  # noqa: E402 — populated by conftest.py sys.path injection
from tests.conformance_vectors import (
    Vector,
    detector_findings_for_rule,
    findings_match,
    load_vectors,
)


_VECTORS: list[Vector] = load_vectors()


def _ids(vec: Vector) -> str:
    return f"{vec.test_id} [{vec.category}]"


@pytest.mark.parametrize("vector", _VECTORS, ids=_ids)
def test_conformance_vector(vector: Vector) -> None:
    report = sild_detector.analyse_fhir_bundle(vector.bundle)
    actual  = detector_findings_for_rule(report, vector.rule)
    ok, why = findings_match(actual, vector.expected_findings, bundle=vector.bundle)
    assert ok, (
        f"Vector {vector.test_id} ({vector.category}) did not match:\n"
        f"  rule:        {vector.rule}\n"
        f"  description: {vector.description}\n"
        f"  expected:    {vector.expected_findings}\n"
        f"  actual:      {actual}\n"
        f"  reason:      {why}"
    )
