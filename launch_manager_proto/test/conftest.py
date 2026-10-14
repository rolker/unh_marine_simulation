# Copyright 2026 Roland Arsenault, UNH CCOM
"""Make the package and the test helpers importable when pytest runs from a checkout."""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.dirname(HERE))
