"""HALS Studio entry point; dispatch frozen worker processes before Qt imports."""
import multiprocessing

if __name__ == '__main__':
    multiprocessing.freeze_support()
    from app import main
    raise SystemExit(main())
