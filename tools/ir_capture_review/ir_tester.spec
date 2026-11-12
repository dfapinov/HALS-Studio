from pathlib import Path
import sys

root = Path(SPECPATH)
repo = root.parents[1]
packages = ['numpy', 'scipy', 'matplotlib', 'contourpy', 'cycler', 'fonttools',
            'kiwisolver', 'packaging', 'pillow', 'pyparsing', 'python-dateutil', 'six']
data = [(str(root/'README.md'), '.'), (str(repo/'LICENSE'), '.')]
data += [(str(repo/'licenses'/name), 'licenses/'+name) for name in packages]
data += [(str(Path(sys.base_prefix)/'LICENSE.txt'), 'licenses/Python')]
a = Analysis([str(root/'packaged_entry.py')], pathex=[str(root)], binaries=[],
    datas=data, hiddenimports=['matplotlib.backends.backend_tkagg'],
    hookspath=[], hooksconfig={'matplotlib': {'backends': ['TkAgg']}},
    excludes=['PySide6', 'PyQt6', 'PyQt5', 'PySide2', 'vtk', 'vtkmodules', 'pandas',
              'IPython', 'notebook', 'pytest', 'sphinx'], noarchive=False)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name='HALS IR Tester',
    console=False, debug=False, strip=False, upx=False,
    icon=str(repo/'src/hals_studio/resources/studio.ico'))
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name='HALS IR Tester')
