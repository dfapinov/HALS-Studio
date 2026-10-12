"""Source/frozen launcher; dispatch multiprocessing before importing Qt."""
import multiprocessing
import sys
from pathlib import Path

if __name__ == '__main__':
    multiprocessing.freeze_support()
    if not getattr(sys, 'frozen', False):
        sys.path.insert(0, str(Path(__file__).resolve().parent / 'src'))
    if len(sys.argv) == 3 and sys.argv[1] == '--self-test':
        from hals_studio.infrastructure.frozen_check import run
        raise SystemExit(run(sys.argv[2]))
    from hals_studio.ui.app import main
    raise SystemExit(main())
