# HALS Studio Windows bundle. Run build.ps1 from this independent repository.
from pathlib import Path
from PyInstaller.utils.hooks import collect_data_files, collect_submodules
root = Path(SPECPATH)
data = [(str(root/'src/hals_studio/resources'), 'resources'),
        (str(root/'README.md'), '.'), (str(root/'documentation'), 'documentation'),
        (str(root/'licenses'), 'licenses'), (str(root/'LICENSE'), '.')]
# Keep the application source available as described in licenses/Qt/NOTICE.txt.
data += [(str(path), str(Path('source') / path.parent.relative_to(root)))
         for path in (root / 'src' / 'hals_studio').rglob('*.py')]
data += [(str(root / 'entry.py'), 'source')]
for package in ('pyvista', 'pyvistaqt'):
    data += collect_data_files(package)
hidden = ['scipy.special', 'scipy.spatial.transform', 'pandas', 'tkinter',
          'matplotlib.backends.backend_tkagg', 'vtkmodules.all', 'vtkmodules.util.numpy_support']
hidden += collect_submodules('hals_studio')
hidden += collect_submodules('pyvista', filter=lambda n: '.examples' not in n and '.jupyter' not in n and '.trame' not in n)
a = Analysis([str(root/'entry.py')], pathex=[str(root/'src')],
             binaries=[], datas=data, hiddenimports=hidden,
             excludes=['PyQt5', 'PyQt6', 'PySide2', 'IPython', 'notebook', 'pytest', 'sphinx', 'trame'], noarchive=False)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name='HALS Studio', console=False,
          debug=False, strip=False, upx=False, icon=str(root/'src/hals_studio/resources/studio.ico'))
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name='HALS Studio')
