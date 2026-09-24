"""HALS Studio entry point; dispatch frozen worker processes before Qt imports."""
import multiprocessing

if __name__ == '__main__':
    multiprocessing.freeze_support()
    import sys
    if len(sys.argv) == 3 and sys.argv[1] == '--self-test':
        from frozen_check import run
        raise SystemExit(run(sys.argv[2]))
    from app import main
    raise SystemExit(main())
