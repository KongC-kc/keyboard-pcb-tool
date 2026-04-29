"""Module entry point: python -m keyboard_pcb_tool"""

import sys
import os

# Ensure package dir is on path for internal imports
_pkg_dir = os.path.dirname(os.path.abspath(__file__))
if _pkg_dir not in sys.path:
    sys.path.insert(0, _pkg_dir)

from main import main

if __name__ == "__main__":
    main()
