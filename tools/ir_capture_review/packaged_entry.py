"""Windows bundle entry point; keep generated runtime state in one owned folder."""
import os
from pathlib import Path
import sys

if getattr(sys, 'frozen', False):
    cache = Path(os.environ['LOCALAPPDATA'])/'HALS IR Tester'/'cache'
    os.environ['MPLCONFIGDIR'] = str(cache/'matplotlib')
    os.environ['XDG_CACHE_HOME'] = str(cache)

from ir_capture_review import main

if __name__ == '__main__':
    if len(sys.argv) == 4 and sys.argv[1] == '--smoke-test':
        import json
        import traceback
        import tkinter as tk
        from ir_capture_review import ReviewApp
        from ir_capture_quality import scan_directory
        output = Path(sys.argv[3])
        root = None
        try:
            root = tk.Tk()
            root.withdraw()
            app = ReviewApp(root)
            app.folder = Path(sys.argv[2])
            app.rows = scan_directory(app.folder)
            app.populate()
            app.tree.selection_set('0')
            app.inspect()
            app.canvas.draw()
            if len(app.figure.axes) != 5:
                raise RuntimeError(app.details.get())
            output.write_text(json.dumps({'rows': len(app.rows), 'plots': 5,
                'titles': [ax.get_title() for ax in app.figure.axes],
                'cache': os.environ.get('MPLCONFIGDIR')}), encoding='utf-8')
        except Exception:
            output.write_text(traceback.format_exc(), encoding='utf-8')
            raise
        finally:
            if root is not None:
                root.destroy()
    else:
        main()
