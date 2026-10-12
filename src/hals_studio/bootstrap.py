"""Resolve optional local dependencies without changing HALS's environment."""
import os
import sys
from pathlib import Path

HERE = Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parents[2]))
RESOURCES = (HERE / 'resources') if getattr(sys, 'frozen', False) else Path(__file__).resolve().parent / 'resources'
ROOT = Path.home() / 'Documents' if getattr(sys, 'frozen', False) else HERE
CACHE_ROOT = (Path(os.environ.get('LOCALAPPDATA', Path.home())) / 'HALS Studio' / 'cache') if getattr(sys, 'frozen', False) else HERE / 'process_cache'
os.environ.setdefault("QT_API", "pyside6")
os.environ.setdefault("OMP_NUM_THREADS", "1")
for key in ("OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
    os.environ[key] = "1"
