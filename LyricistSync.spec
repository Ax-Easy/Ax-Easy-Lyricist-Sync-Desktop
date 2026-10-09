# PyInstaller spec: one-folder, windowed LyricistSync.exe (GUI + bootstrap; PyTorch is NOT bundled).
import glob, os
from PyInstaller.utils.hooks import collect_submodules

ROOT = os.path.abspath('.')
datas = [
    ('app/lyricist_sync/manifest.json', 'lyricist_sync'),
    ('app/lyricist_sync/res/*', 'lyricist_sync/res'),
    ('engine/lyricist_engine.py', 'engine'),
    ('engine/timing.py', 'engine'),
    ('engine/transcribe.py', 'engine'),
    ('THIRD_PARTY_NOTICES.md', '.'),
    ('LICENSE', '.'),
]
datas += [(w, 'wheels') for w in glob.glob('wheels/*.whl')]

a = Analysis(
    ['LyricistSync.py'],
    pathex=[os.path.join(ROOT, 'app')],
    datas=datas,
    hiddenimports=collect_submodules('lyricist_sync') + ['PySide6.QtSvg', 'PySide6.QtMultimedia'],
    excludes=['tkinter', 'PySide6.QtWebEngineCore', 'PySide6.QtWebEngineWidgets', 'PySide6.QtQuick', 'PySide6.QtQml',
              'PySide6.Qt3DCore', 'PySide6.QtCharts', 'PySide6.QtDataVisualization', 'PySide6.QtPdf', 'PySide6.QtQuick3D',
              'PySide6.QtDesigner', 'PySide6.QtBluetooth', 'PySide6.QtLocation', 'PySide6.QtPositioning', 'PySide6.QtSql',
              'PySide6.QtTest', 'PySide6.QtWebSockets', 'PySide6.QtSerialPort', 'PySide6.QtRemoteObjects',
              'PySide6.QtSpatialAudio', 'PySide6.QtGraphs', 'PySide6.QtHttpServer', 'numpy', 'mutagen'],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name='LyricistSync', console=False, debug=False,
          icon='installer/LyricistSync.ico', version='installer/version_info.txt', upx=False)
coll = COLLECT(exe, a.binaries, a.datas, name='LyricistSync', upx=False)
