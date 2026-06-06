"""Pytest config: put code/ (parent of tests/) on sys.path.

The pipeline runs modules with code/ as the import root (e.g. ``import config``,
``import tenure``), so tests must import the same way.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
