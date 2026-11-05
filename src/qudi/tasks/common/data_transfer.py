# -*- coding: utf-8 -*-
"""
qudi-core-HiM: copy of the data of a task run to a server folder, in the background.

DataTransfer(log, destination_root, timeout_s=300) is independent of the microscope and of ZEN. Every
network operation (creating folders, the write test, copying, renaming) runs in ONE background thread
(threading.Thread + queue.Queue, daemon), inside try/except: the calling task thread never touches the
server, so a server or network problem can never crash or block the task. Errors go to the task log.

  - add(src_path, relative_dest): queue a file for <destination_root>/<relative_dest> (a file already queued,
    being copied or sent is ignored); discard(src_paths): take files out of the queue.
  - allow() / pause(): files are copied only while the transfer is allowed (paused at creation); pause() does
    not interrupt a copy in progress.
  - server_ok: False after a failed copy or write test (one warning when the connection is lost, one info
    message when it is back). While the server is down, the thread does a write test (small file created and
    removed in destination_root, which it creates) every RETRY_PERIOD_S and resumes when it passes.
  - test(timeout_s) -> bool: write test done now by the thread, waited for at most timeout_s.
  - wait_idle(timeout_s) -> bool: wait until no copy is in progress (not until the queue is empty); True at
    once while the server is down; on timeout: warning, server_ok = False, False (a copy stuck on the network
    cannot be killed; the thread starts no new copy while wait_idle runs).
  - flush(timeout_s) -> list: allow the transfer and wait until the queue is empty, the timeout is reached or
    the server is down; returns the local paths not sent.
  - stop(): stop the thread (does not wait for a stuck copy).

Copy of one file: destination folder created, shutil.copyfile to <dest>.part, size checked against the
source, os.replace to <dest>; a destination that already exists with the size of the source counts as sent.
A file is marked sent only after os.replace succeeded. Any error: warning with the exception, <dest>.part
removed if possible, the file is queued again and the server marked as down.

Modified with Claude code (Anthropic)

-----------------------------------------------------------------------------------
qudi-core is free software: you can redistribute it and/or modify it under the terms of the GNU General Public License
as published by the Free Software Foundation, either version 3 of the License, or (at your option) any later version.

Qudi is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU General Public License for more details.

You should have received a copy of the GNU General Public License along with Qudi. If not, see <http://www.gnu.org/licenses/>.
-----------------------------------------------------------------------------------
"""

__all__ = ['DataTransfer', 'RETRY_PERIOD_S']

import os
import queue
import shutil
import threading
import uuid
from time import monotonic

RETRY_PERIOD_S = 60   # write test of the server folder every RETRY_PERIOD_S while it is down
_IDLE_WAIT_S = 0.1    # idle loop period of the transfer thread
PART_SUFFIX = '.part'


class DataTransfer:
    """Background copy of files to destination_root (see the module docstring)."""

    def __init__(self, log, destination_root, timeout_s=300):
        self.log = log
        self.destination_root = str(destination_root)
        self.timeout_s = float(timeout_s)
        self.server_ok = True          # until a copy or a write test fails
        self._reported_down = False    # the 'not reachable' warning was logged, no 'reachable again' yet
        self._queue = queue.Queue()    # (src, relative_dest)
        self._queued = set()           # src queued or being copied
        self._sent = set()             # src sent
        self._lock = threading.Lock()
        self._allowed = threading.Event()   # copies only while set (paused at creation)
        self._hold = threading.Event()      # set by wait_idle: no new copy
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._idle = threading.Event()      # set while no copy is in progress
        self._idle.set()
        self._test_requests = queue.Queue()  # events of test() calls, answered by the thread
        self._last_test = None
        self._current = None
        self._thread = threading.Thread(target=self._loop, name='data_transfer', daemon=True)
        self._thread.start()

    # ------------------------------------------------------------------ calling thread
    def add(self, src_path, relative_dest) -> None:
        """Queue src_path for <destination_root>/<relative_dest>; ignored when already queued or sent."""
        with self._lock:
            if src_path in self._queued or src_path in self._sent:
                return
            self._queued.add(src_path)
        self._queue.put((src_path, relative_dest))
        self._wake.set()

    def allow(self) -> None:
        self._allowed.set()
        self._wake.set()

    def pause(self) -> None:
        self._allowed.clear()

    def discard(self, src_paths) -> list:
        """Remove these files from the queue (a copy in progress is not stopped); returns the files removed."""
        src_paths = set(src_paths)
        removed, kept = [], []
        with self._lock:
            while True:
                try:
                    item = self._queue.get_nowait()
                except queue.Empty:
                    break
                (removed if item[0] in src_paths else kept).append(item)
            for item in kept:
                self._queue.put(item)
            for src, _ in removed:
                self._queued.discard(src)
        return sorted(src for src, _ in removed)

    def is_sent(self, src_path) -> bool:
        with self._lock:
            return src_path in self._sent

    def pending(self) -> list:
        """Local paths not sent yet (queued or being copied)."""
        with self._lock:
            return sorted(self._queued)

    def test(self, timeout_s) -> bool:
        """Write test of destination_root done now by the transfer thread; False if it fails or does not finish
        within timeout_s (the thread may be stuck on the network)."""
        done = threading.Event()
        result = {}
        self._test_requests.put((done, result))
        self._wake.set()
        if not done.wait(timeout_s):
            self._set_server(False, f'write test of {self.destination_root} not finished after {timeout_s:g} s')
            return False
        return result.get('ok', False)

    def wait_idle(self, timeout_s) -> bool:
        """Wait until no copy is in progress. True at once while the server is down; on timeout: warning,
        server_ok = False, False. No new copy starts while it waits."""
        if not self.server_ok:
            return True
        self._hold.set()
        try:
            if self._idle.wait(timeout_s):
                return True
            self._set_server(False, f'copy of {self._current} not finished after {timeout_s:g} s')
            return False
        finally:
            self._hold.clear()
            self._wake.set()

    def flush(self, timeout_s) -> list:
        """Allow the transfer and wait until every queued file is sent, the timeout is reached or the server is
        down; returns the local paths not sent."""
        self.allow()
        deadline = monotonic() + float(timeout_s)
        while monotonic() < deadline and self.server_ok and self.pending():
            self._stop.wait(min(0.05, max(0.0, deadline - monotonic())))
        return self.pending()

    def stop(self) -> None:
        """Stop the thread; a copy stuck on the network is not waited for."""
        self._stop.set()
        self._wake.set()
        self._thread.join(timeout=1.0)

    # ------------------------------------------------------------------ transfer thread
    def _set_server(self, ok, reason='') -> None:
        """Server state. One warning when the connection is lost and one info message when it is back: the
        'reachable again' message waits for a successful copy (or a passed write test with nothing to copy), so
        a server that passes the write test but still fails the copies does not repeat both messages."""
        self.server_ok = ok
        if not ok and not self._reported_down:
            self._reported_down = True
            self.log.warning(f'Data transfer: server folder {self.destination_root} not reachable ({reason}) - '
                             f'the experiment continues, the files will be sent when the server is back '
                             f'(test every {RETRY_PERIOD_S} s)')

    def _report_back(self) -> None:
        if self._reported_down:
            self._reported_down = False
            self.log.info(f'Data transfer: server folder {self.destination_root} reachable again - transfer resumed')

    def _write_test(self) -> bool:
        """Create destination_root, write and remove a small file there."""
        self._last_test = monotonic()
        try:
            os.makedirs(self.destination_root, exist_ok=True)
            path = os.path.join(self.destination_root, f'.qudi_write_test_{uuid.uuid4().hex}')
            with open(path, 'w') as stream:
                stream.write('qudi write test\n')
            os.remove(path)
        except Exception as err:
            self._set_server(False, f'write test: {err}')
            return False
        self._set_server(True)
        if self._queue.empty():
            self._report_back()
        return True

    def _copy(self, src, relative_dest) -> None:
        """Copy one file (<dest>.part, size check, os.replace); on error the file is queued again."""
        dest = os.path.join(self.destination_root, relative_dest)
        part = dest + PART_SUFFIX
        try:
            size = os.path.getsize(src)
            if os.path.isfile(dest) and os.path.getsize(dest) == size:
                sent = True  # already on the server
            else:
                os.makedirs(os.path.dirname(dest) or self.destination_root, exist_ok=True)
                shutil.copyfile(src, part)
                if os.path.getsize(part) != size:
                    raise OSError(f'size of the copy {os.path.getsize(part)} B instead of {size} B')
                os.replace(part, dest)
                sent = True
        except Exception as err:
            self.log.warning(f'Data transfer: could not copy {src} to {dest}: {err!r}')
            try:
                if os.path.exists(part):
                    os.remove(part)
            except Exception:
                pass
            self._queue.put((src, relative_dest))  # retried when the server is back
            self._set_server(False, f'copy failed: {err}')
            return
        if sent:
            with self._lock:
                self._queued.discard(src)
                self._sent.add(src)
            self._set_server(True)  # e.g. a copy that was stuck on the network finally went through
            self._report_back()

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                # write tests asked by test()
                while not self._test_requests.empty():
                    done, result = self._test_requests.get_nowait()
                    result['ok'] = self._write_test()
                    done.set()
                # server down: write test every RETRY_PERIOD_S
                if not self.server_ok:
                    if self._last_test is None or monotonic() - self._last_test >= RETRY_PERIOD_S:
                        self._write_test()
                    if not self.server_ok:
                        self._wake.wait(min(_IDLE_WAIT_S, RETRY_PERIOD_S))
                        self._wake.clear()
                        continue
                # copy the next file while allowed (no new copy while wait_idle waits)
                if self._allowed.is_set() and not self._hold.is_set() and not self._queue.empty():
                    src, relative_dest = self._queue.get_nowait()
                    self._current = src
                    self._idle.clear()
                    try:
                        self._copy(src, relative_dest)
                    finally:
                        self._current = None
                        self._idle.set()
                    continue
                self._wake.wait(_IDLE_WAIT_S)
                self._wake.clear()
            except Exception as err:  # never let the thread die
                try:
                    self.log.error(f'Data transfer: unexpected error {err!r}')
                except Exception:
                    pass
                self._stop.wait(_IDLE_WAIT_S)
