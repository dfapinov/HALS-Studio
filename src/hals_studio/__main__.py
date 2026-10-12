"""Launch HALS Studio as a module."""
import multiprocessing

if __name__ == '__main__':
    multiprocessing.freeze_support()
    from .ui.app import main
    raise SystemExit(main())
