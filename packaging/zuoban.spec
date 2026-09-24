# Windows Qt6 requires Windows' ICU API. An unrelated ICU on PATH can be
# mistakenly copied by dependency discovery; it exports suffixed symbols and
# breaks Qt6Core. Do not redistribute it, use the supported Windows system ICU.
from pathlib import Path
from PyInstaller.utils.hooks import collect_all

root = Path(SPECPATH).parent
datas, binaries, hiddenimports = collect_all(
    'mediapipe', filter_submodules=lambda name: not name.startswith((
        'mediapipe.tasks.python.test', 'mediapipe.tasks.python.benchmark',
        'mediapipe.tasks.python.metadata')))
datas.append((str(root / 'models'), 'models'))
a = Analysis([str(root / 'main.py')], pathex=[str(root)], binaries=binaries,
             datas=datas, hiddenimports=hiddenimports, hookspath=[], runtime_hooks=[],
             excludes=['pytest', 'reportlab'], noarchive=False)
a.binaries = [entry for entry in a.binaries
              if Path(entry[0]).name.lower() not in ('icuuc.dll', 'icudt78.dll')]
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name='ZuoBan',
          debug=False, bootloader_ignore_signals=False, strip=False, upx=False,
          console=False, disable_windowed_traceback=False)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name='ZuoBan')
