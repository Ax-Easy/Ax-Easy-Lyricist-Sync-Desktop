"""PyInstaller entry point for LyricistSync.exe."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'app'))

from lyricist_sync.cli import main  # noqa: E402

if __name__ == '__main__':
    sys.exit(main())
