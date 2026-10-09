import os
import sys


def app_dir():
    """Folder with engine/ and wheels/ (PyInstaller _MEIPASS when frozen, repo root otherwise)."""
    if getattr(sys, 'frozen', False):
        return getattr(sys, '_MEIPASS', os.path.dirname(sys.executable))
    return os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))


def home():
    """%LOCALAPPDATA%\\Ax-Easy\\LyricistSync on Windows, ~/Library/Application Support/Ax-Easy/LyricistSync
    on macOS (override with LYRICIST_SYNC_HOME)."""
    h = os.environ.get('LYRICIST_SYNC_HOME')
    if not h:
        if sys.platform == 'darwin':
            base = os.path.join(os.path.expanduser('~'), 'Library', 'Application Support')
        else:
            base = os.environ.get('LOCALAPPDATA') or os.path.join(os.path.expanduser('~'), '.local', 'share')
        h = os.path.join(base, 'Ax-Easy', 'LyricistSync')
    os.makedirs(h, exist_ok=True)
    return h


def models_dir():
    return os.path.join(home(), 'models')


def runtime_python(h=None):
    h = h or home()
    if os.environ.get('LYRICIST_SYNC_PYTHON'):  # developer override (e.g. a Linux venv)
        return os.environ['LYRICIST_SYNC_PYTHON']
    if os.name == 'nt':
        return os.path.join(h, 'runtime', 'python', 'python.exe')
    return os.path.join(h, 'runtime', 'python', 'bin', 'python3')


def engine_script():
    return os.path.join(app_dir(), 'engine', 'lyricist_engine.py')


def resource(*p):
    return os.path.join(app_dir(), 'app', 'lyricist_sync', *p) if not getattr(sys, 'frozen', False) \
        else os.path.join(app_dir(), 'lyricist_sync', *p)
