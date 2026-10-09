# PyInstaller spec (macOS): "Lyricist Sync.app", universal2 (Apple Silicon + Intel in one bundle),
# GUI + bootstrap only; PyTorch is downloaded by the first-run setup for this Mac's architecture.
# Build with a universal2 Python (python.org 3.12 installer) and the universal2 PySide6 6.7 wheels.
import glob, os, re
from PyInstaller.utils.hooks import collect_submodules

ROOT = os.path.abspath('.')
VERSION = re.search(r'VERSION = "([^"]+)"', open(os.path.join(ROOT, 'app', 'lyricist_sync', '__init__.py')).read()).group(1)
datas = [
    ('app/lyricist_sync/manifest.json', 'lyricist_sync'),
    ('app/lyricist_sync/manifest-mac.json', 'lyricist_sync'),
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
              'PySide6.QtSpatialAudio', 'PySide6.QtGraphs', 'PySide6.QtHttpServer', 'numpy'],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name='LyricistSync', console=False, debug=False,
          upx=False, target_arch='universal2', argv_emulation=False,
          codesign_identity=None, entitlements_file='mac/entitlements.plist')
coll = COLLECT(exe, a.binaries, a.datas, name='LyricistSync', upx=False)
app = BUNDLE(
    coll,
    name='Lyricist Sync.app',
    icon='mac/LyricistSync.icns',
    bundle_identifier='com.ax-easy.lyricistsync',
    version=VERSION,
    info_plist={
        'CFBundleName': 'Lyricist Sync',
        'CFBundleDisplayName': 'Lyricist Sync',
        'CFBundleShortVersionString': VERSION,
        'CFBundleVersion': VERSION,
        'NSHumanReadableCopyright': 'Copyright © 2026 Ax-Easy (Evangelos Makrydakis). All rights reserved.',
        'LSApplicationCategoryType': 'public.app-category.music',
        # macOS 11 Big Sur on Apple Silicon, macOS 12 Monterey on Intel (Qt 6.7 runs on 11+;
        # the Intel engine stack is tested on 12+)
        'LSMinimumSystemVersion': '11.0',
        'LSMinimumSystemVersionByArchitecture': {'arm64': '11.0', 'x86_64': '12.0'},
        'LSArchitecturePriority': ['arm64', 'x86_64'],
        'NSHighResolutionCapable': True,
        # the frozen python.org OpenSSL has no CA bundle of its own on users' Macs (cli._mac_ca_bundle too)
        'LSEnvironment': {'SSL_CERT_FILE': '/etc/ssl/cert.pem'},
        'NSRequiresAquaSystemAppearance': False,
        'NSSupportsAutomaticGraphicsSwitching': True,
        'CFBundleDocumentTypes': [{
            'CFBundleTypeName': 'Audio',
            'CFBundleTypeRole': 'Viewer',
            'LSHandlerRank': 'Alternate',
            'LSItemContentTypes': ['public.audio', 'public.mp3', 'com.microsoft.waveform-audio', 'org.xiph.flac',
                                   'public.mpeg-4-audio', 'public.aac-audio'],
        }],
    },
)
