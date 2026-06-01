"""
heimdall/__main__.py

Allows running as a module:  python -m heimdall
Equivalent to:               python run.py
"""

import runpy
import sys
from pathlib import Path

# Run run.py from the repo root
run_py = Path(__file__).parent.parent / "run.py"
sys.argv[0] = str(run_py)
runpy.run_path(str(run_py), run_name="__main__")
