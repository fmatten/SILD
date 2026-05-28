"""
Make sild_monitoring_stack/ importable as a top-level package directory so
the detector can be invoked from the pytest session.
"""
import sys
from pathlib import Path

REPO_ROOT  = Path(__file__).resolve().parents[1]
STACK_PATH = REPO_ROOT / "sild_monitoring_stack"

if str(STACK_PATH) not in sys.path:
    sys.path.insert(0, str(STACK_PATH))
