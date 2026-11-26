"""Paths shared by source and frozen Workbench runtimes."""
from pathlib import Path

import backend


def probe_directory():
    # The frozen executable entry can live outside the backend package.
    return Path(backend.__file__).parent / "probes"


BACKEND_ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = BACKEND_ROOT.parent
PROBES_DIR = probe_directory()
SKILLS_DIR = BACKEND_ROOT / "skills"
