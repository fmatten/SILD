"""
Parser + adapter for "SILD Conformance Test Vectors v0.1.md".

The Markdown file embeds multiple YAML documents inside ```yaml fenced code
blocks. Two complications make a vanilla yaml.safe_load_all() insufficient:

  1. Multiple test vectors share one fenced block, with NO `---` document
     separator. Each new vector starts at a column-0 `test_id:` line.
  2. Some fenced blocks contain rule *definitions* (id:/pattern:/path:/...)
     instead of test vectors. Those must be ignored.

This module:
  - extracts fenced YAML blocks from the Markdown,
  - splits each block on column-0 `test_id:` boundaries,
  - returns one dict per parsed vector,
  - exposes a small adapter that runs sild_detector.analyse_fhir_bundle()
    on a vector's input and maps the detector's LossEvent objects into the
    abstract finding format the vectors compare against.

The adapter is deliberately strict on (pattern, severity, resource-type)
and lenient on field-level path: the current detector tracks location at
the resource granularity (e.g. "Observation/obs-001"), whereas vectors
specify field-level paths (e.g. "Observation.code"). The lenient-path
behaviour is intentional and documented; closing this gap is open work.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import yaml

VECTORS_MD = Path(__file__).resolve().parents[1] / "SILD Conformance Test Vectors v0.1.md"

_FENCE_RE     = re.compile(r"^```yaml\s*$(.*?)^```\s*$", re.MULTILINE | re.DOTALL)
_TEST_ID_LINE = re.compile(r"^test_id:\s", re.MULTILINE)

# Some `description:` values contain additional unquoted colons (e.g.
# `description: Foo uses urn:uuid: ...`). PyYAML rejects those as ambiguous
# mappings. Pre-quote such scalars so they parse as strings.
_UNQUOTED_DESC = re.compile(
    r"^(description:\s+)(?!['\"\|>])(.*:.*)$", re.MULTILINE
)


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
    bundle:            dict
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


def _prequote_descriptions(yaml_text: str) -> str:
    def _quote(m: re.Match) -> str:
        prefix, value = m.group(1), m.group(2).rstrip()
        # don't double-quote, but do escape embedded double quotes
        return f'{prefix}"{value.replace(chr(34), chr(92) + chr(34))}"'
    return _UNQUOTED_DESC.sub(_quote, yaml_text)


def _parse_one_vector(yaml_text: str) -> Vector:
    raw = yaml.safe_load(_prequote_descriptions(yaml_text))
    return Vector(
        test_id=raw["test_id"],
        rule=raw["rule"],
        category=raw["category"],
        description=raw["description"],
        bundle=raw["input"],
        expected_findings=raw.get("expected_findings", []),
        source_context=raw.get("source_context"),
        notes=raw.get("notes"),
    )


def load_vectors(md_path: Path = VECTORS_MD) -> list[Vector]:
    """Parse every test vector in the conformance Markdown document."""
    text = md_path.read_text(encoding="utf-8")
    vectors: list[Vector] = []
    for m in _FENCE_RE.finditer(text):
        block = m.group(1)
        for piece in _split_vectors_in_block(block):
            vectors.append(_parse_one_vector(piece))
    return vectors


# --- adapter: detector -> abstract findings -----------------------------

def _resource_type_from_location(loc: str) -> str:
    """detector location is 'ResourceType/id' or just 'X/1' or '?'; take prefix."""
    return loc.split("/", 1)[0] if "/" in loc else loc


def _vector_resource_type_from_path(path: str) -> str:
    """vector path is 'ResourceType.field' or 'ResourceType.field.subfield'."""
    return path.split(".", 1)[0] if "." in path else path


def detector_findings_for_rule(report, rule: str) -> list[dict]:
    """
    Translate sild_detector.SILDReport.losses into the abstract finding shape
    used by the conformance vectors, FILTERED to those matching the given
    rule's pattern. Returns list of dicts with keys:
      rule_id, pattern, detected_severity, path
    """
    # Map rule prefix (e.g. 'TN-CC-01' -> 'TN') to detector pattern value
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
            # field-level path not tracked by detector; expose resource-level
            "path":              _resource_type_from_location(loss.location),
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
    Path comparison is currently RESOURCE-LEVEL by default: the detector
    locates findings at 'ResourceType/id', while vectors say
    'ResourceType.field'. We compare only the resource-type prefix. Set
    strict_path=True once the detector tracks field-level paths.
    """
    if len(actual) != len(expected):
        return False, (
            f"finding count differs: expected={len(expected)}, "
            f"actual={len(actual)}"
        )

    remaining = list(actual)
    for exp in expected:
        exp_rt = _vector_resource_type_from_path(exp.get("path", ""))
        for i, act in enumerate(remaining):
            if act["pattern"] != exp["pattern"]:
                continue
            if act["detected_severity"] != exp["detected_severity"]:
                continue
            if strict_path:
                if act["path"] != exp.get("path", ""):
                    continue
            else:
                if act["path"] != exp_rt:
                    continue
            remaining.pop(i)
            break
        else:
            return False, f"no actual finding matches expected={exp}"
    return True, "ok"
