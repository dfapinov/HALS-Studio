# HALS Studio Windows bundle. Run build.ps1 from this independent repository.
from pathlib import Path
from PyInstaller.utils.hooks import collect_data_files, collect_submodules
root = Path(SPECPATH)
data = [(str(root/'studio.ico'), '.'), (str(root/'README.md'), '.'),
        (str(root/'process_schema.json'), '.'), (str(root/'assets'), 'assets'),
        (str(root/'images'), 'images'), (str(root/'documentation'), 'documentation'),
        (str(root/'licenses'), 'licenses'), (str(root/'LICENSE'), '.')]
# Bootstrap and the processing host resolve these modules dynamically.
for folder in ('process_engine', 'hals_engine', 'misc'):
    data += [(str(p), str(p.parent.relative_to(root))) for p in (root/folder).rglob('*.py')]
for package in ('pyvista', 'pyvistaqt'):
    data += collect_data_files(package)
hidden = ['scipy.special', 'scipy.spatial.transform', 'pandas', 'tkinter',
          'matplotlib.backends.backend_tkagg', 'vtkmodules.all', 'vtkmodules.util.numpy_support']
for folder in ('process_engine', 'hals_engine'):
    hidden += [folder+'.'+p.stem for p in (root/folder).glob('*.py')]
    hidden += [p.stem for p in (root/folder).glob('*.py')]
hidden += ['spatial_error_viewer']
hidden += collect_submodules('pyvista', filter=lambda n: '.examples' not in n and '.jupyter' not in n and '.trame' not in n)
a = Analysis([str(root/'entry.py')], pathex=[str(root), str(root/'_vendor'), str(root/'hals_engine'), str(root/'process_engine'), str(root/'misc')],
             binaries=[], datas=data, hiddenimports=hidden,
             excludes=['PyQt5', 'PyQt6', 'PySide2', 'IPython', 'notebook', 'pytest', 'sphinx', 'trame'], noarchive=False)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name='HALS Studio', console=False,
          debug=False, strip=False, upx=False, icon=str(root/'studio.ico'))
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name='HALS Studio')
