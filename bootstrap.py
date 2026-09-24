"""Resolve optional local dependencies without changing HALS's environment."""
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = Path.home() / 'Documents' if getattr(sys, 'frozen', False) else HERE
if (HERE / "_vendor").is_dir():
    sys.path.insert(0, str(HERE / "_vendor"))
sys.path.insert(0, str(HERE / "hals_engine"))
sys.path.append(str(HERE / "misc"))
CACHE_ROOT = (Path(os.environ.get("LOCALAPPDATA", Path.home())) / "HALS Studio" / "cache") if getattr(sys, "frozen", False) else HERE / "process_cache"
# All viewer workspaces share the real viewer-owned processing pool. The older
# Stage 5 snapshot contains a no-op session_pool shim; never cache that shim.
if 'session_pool' not in sys.modules and (HERE/'process_engine/session_pool.py').is_file():
    import importlib.util
    spec=importlib.util.spec_from_file_location('session_pool',HERE/'process_engine/session_pool.py')
    module=importlib.util.module_from_spec(spec);sys.modules['session_pool']=module;spec.loader.exec_module(module)
os.environ.setdefault("QT_API", "pyside6")
os.environ.setdefault("OMP_NUM_THREADS", "1")
for key in ("OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
    os.environ[key] = "1"
