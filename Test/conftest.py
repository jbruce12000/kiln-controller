import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
LIB = os.path.join(ROOT, 'lib')

for path in (ROOT, LIB):
    if path not in sys.path:
        sys.path.insert(0, path)
