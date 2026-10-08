"""Runs the engine (lyricist_engine.py in the downloaded Python) as a hidden child process
and turns its JSON-lines output into Qt signals."""
import json
import os
import subprocess
import threading

from PySide6.QtCore import QObject, Signal

from . import bootstrap, paths


class EngineClient(QObject):
    hello = Signal(object)
    progress = Signal(str, str, float)
    result = Signal(str, object)
    error = Signal(str, str)
    exited = Signal(int)

    def __init__(self, device='auto', parent=None):
        super().__init__(parent)
        self.device = device
        self.proc = None
        self.log_path = os.path.join(paths.home(), 'engine.log')

    def running(self):
        return self.proc is not None and self.proc.poll() is None

    def start(self):
        if self.running():
            return
        py = paths.runtime_python()
        args = [py, '-u', paths.engine_script(), '--models', paths.models_dir(), '--device', self.device, 'serve']
        self._log = open(self.log_path, 'a', encoding='utf-8', errors='replace')
        self.proc = bootstrap.popen(args, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=self._log,
                                    env=bootstrap.engine_env(), creationflags=bootstrap.NO_WINDOW, cwd=paths.home())
        threading.Thread(target=self._reader, args=(self.proc,), daemon=True).start()

    def _reader(self, proc):
        for raw in proc.stdout:
            try:
                ev = json.loads(raw.decode('utf-8', 'replace'))
            except ValueError:
                continue
            kind = ev.get('event')
            if kind == 'hello':
                self.hello.emit(ev)
            elif kind == 'progress':
                self.progress.emit(str(ev.get('id')), ev.get('stage', ''), float(ev.get('pct', 0)))
            elif kind == 'result':
                self.result.emit(str(ev.get('id')), ev.get('result'))
            elif kind == 'error':
                self.error.emit(str(ev.get('id')), ev.get('error', 'error'))
        self.exited.emit(proc.wait())

    def submit(self, job):
        self.start()
        self.proc.stdin.write((json.dumps(job, ensure_ascii=False) + '\n').encode('utf-8'))
        self.proc.stdin.flush()

    def stop(self):
        if self.running():
            self.proc.kill()
        self.proc = None
