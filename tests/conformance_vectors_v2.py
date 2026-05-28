"""
Parser + adapter for "SILD Conformance Test Vectors v2 v0.1.md".

Sibling module to conformance_vectors.py — this one handles the HL7 v2
carrier instead of FHIR R4. Two complications make a vanilla
yaml.safe_load_all() insufficient:

  1. Multiple test vectors share one fenced block, with NO `---` document
     separator. Each new vector starts at a column-0 `test_id:` line.
  2. Some fenced blocks contain rule *definitions* (id:/pattern:/path:/...)
     instead of test vectors. Those must be ignored.

This module:
  - extracts fenced YAML blocks from the v2 vectors Markdown,
  - splits each block on column-0 `test_id:` boundaries,
  - returns one dict per parsed vector,
  - exposes a small adapter that runs sild_detector.analyse_hl7_message()
    on a vector's input and maps the detector's LossEvent objects into the
    abstract finding format the vectors compare against.

The adapter is deliberately strict on (pattern, severity, segment-type)
and lenient on field-level path: the current detector tracks location at
the segment granularity (e.g. "OBR/<placer-order-number>"), whereas the
vectors specify field-level paths (e.g. "OBR-4"). Both reduce to the
segment prefix ("OBR") for comparison. This mirrors the FHIR runner's
resource-level lenient-path behaviour and is documented as a roadmap
item — closing the gap to field-level comparison is open work.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import yaml

VECTORS_MD = Path(__file__).resolve().parents[1] / "SILD Conformance Test Vectors v2 v0.1.md"

_FENCE_RE     = re.compile(r"^```yaml\s*$(.*?)^```\s*$", re.MULTILINE | re.DOTALL)
_TEST_ID_LINE = re.compile(r"^test_id:\s", re.MULTILINE)


# --- pattern + severity translation between vector vocabulary and detector ---

_VECTOR_TO_DETECTOR_PATTERN = {
    "TN": "Type Narrowing",
    "TC": "Temporal Collapse",
    "AD": "Attribute Dropping",
    "RS": "Reference Severing",
}
_VECTOR_TO_DETECTOR_SEVERITY = {
    "CRITICAL": "critical",
    "WARNING":  "warning",
    "INFO":     "info",
}


@dataclass
class Vector:
    test_id:           str
    rule:              str
    category:          str   # positive | negative | edge
    description:       str
    message:           str   # raw HL7 v2 message text
    expected_findings: list  # list[dict] in vector vocabulary
    source_context:    Optional[dict] = None
    notes:             Optional[str]  = None

    def __repr__(self) -> str:  # nicer pytest IDs
        return self.test_id


def _split_vectors_in_block(block_text: str) -> list[str]:
    """
    Split a single fenced YAML block on column-0 `test_id:` lines.
    Returns a list of YAML strings, each starting at a `test_id:` line.
    """
    if not _TEST_ID_LINE.search(block_text):
        return []  # not a test-vector block (rule definition etc.)

    starts = [m.start() for m in _TEST_ID_LINE.finditer(block_text)]
    pieces = []
    for i, s in enumerate(starts):
        e = starts[i + 1] if i + 1 < len(starts) else len(block_text)
        pieces.append(block_text[s:e])
    return pieces


def _parse_one_vector(yaml_text: str) -> Vector:
    raw = yaml.safe_load(yaml_text)
    return Vector(
        test_id=raw["test_id"],
        rule=raw["rule"],
        category=raw["category"],
        description=raw["description"],
        message=raw["input"],
        expected_findings=raw.get("expected_findings", []) or [],
        source_context=raw.get("source_context"),
        notes=raw.get("notes"),
    )


def load_vectors(md_path: Path = VECTORS_MD) -> list[Vector]:
    """Parse every test vector in the v2 conformance Markdown document."""
    text = md_path.read_text(encoding="utf-8")
    vectors: list[Vector] = []
    for m in _FENCE_RE.finditer(text):
        block = m.group(1)
        for piece in _split_vectors_in_block(block):
            vectors.append(_parse_one_vector(piece))
    return vectors


# --- adapter: detector -> abstract findings -----------------------------

def _segment_from_detector_location(loc: str) -> str:
    """
    Detector location is 'SEG/<id>' or 'SEG/<obr-id>.OBX<n>' or just 'SEG'.
    Take the segment prefix (everything before the first '/').
    """
    return loc.split("/", 1)[0] if "/" in loc else loc


def _segment_from_vector_path(path: str) -> str:
    """
    Vector path is 'SEG-<field>' (e.g. 'OBR-4') or 'SEG-<field>.<comp>'
    (e.g. 'OBR-4.1'). Take the segment prefix (everything before '-').
    Bare segment names ('OBR') pass through.
    """
    return path.split("-", 1)[0] if "-" in path else path


def detector_findings_for_rule(report, rule: str) -> list[dict]:
    """
    Translate sild_detector.SILDReport.losses (from analyse_hl7_message)
    into the abstract finding shape used by the v2 conformance vectors,
    FILTERED to those matching the given rule's pattern. Returns list of
    dicts with keys: rule_id, pattern, detected_severity, path.

    The `path` is emitted at segment granularity (e.g. 'OBR' / 'OBX' /
    'ORC') matching what the detector currently tracks.
    """
    vector_pattern = rule.split("-", 1)[0]
    detector_pattern = _VECTOR_TO_DETECTOR_PATTERN.get(vector_pattern)
    if detector_pattern is None:
        return []

    out = []
    for loss in report.losses:
        loss_pattern_value = (
            loss.pattern.value if hasattr(loss.pattern, "value") else str(loss.pattern)
        )
        if loss_pattern_value != detector_pattern:
            continue
        out.append({
            "rule_id":           rule,
            "pattern":           vector_pattern,
            "detected_severity": loss.effective_severity.upper(),
            "path":              _segment_from_detector_location(loss.location),
        })
    return out


def findings_match(
    actual: list[dict],
    expected: list[dict],
    *,
    strict_path: bool = False,
) -> tuple[bool, str]:
    """
    Compare actual vs expected findings, order-insensitive.

    Path comparison is currently SEGMENT-LEVEL by default: the detector
    locates findings at 'SEG/<id>', while vectors describe paths as
    'SEG-<field>'. Both reduce to the segment prefix ('OBR', 'OBX',
    'ORC', etc.) for comparison. Set strict_path=True once the detector
    tracks field-level paths (deliberate roadmap, not part of B2).
    """
    if len(actual) != len(expected):
        return False, (
            f"finding count differs: expected={len(expected)}, "
            f"actual={len(actual)}"
        )

    remaining = list(actual)
    for exp in expected:
        exp_seg = _segment_from_vector_path(exp.get("path", ""))
        for i, act in enumerate(remaining):
            if act["pattern"] != exp["pattern"]:
                continue
            if act["detected_severity"] != exp["detected_severity"]:
                continue
            if strict_path:
                if act["path"] != exp.get("path", ""):
                    continue
            else:
                if act["path"] != exp_seg:
                    continue
            remaining.pop(i)
            break
        else:
            return False, f"no actual finding matches expected={exp}"
    return True, "ok"
