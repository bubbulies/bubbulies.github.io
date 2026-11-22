#!/usr/bin/env python3
"""Run the public-site tests; an accidentally empty suite is a failure."""
from pathlib import Path
import sys
import unittest

root = Path(__file__).resolve().parents[1]
suite = unittest.defaultTestLoader.discover(str(root / "PublicSite" / "tests"), top_level_dir=str(root / "PublicSite" / "tests"))
count = suite.countTestCases()
if count == 0:
    sys.exit("No public-site tests discovered; refusing an empty success.")
print(f"Discovered {count} public-site tests.", flush=True)
result = unittest.TextTestRunner(verbosity=2).run(suite)
sys.exit(0 if result.wasSuccessful() and result.testsRun > 0 else 1)
