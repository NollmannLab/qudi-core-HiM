# -*- coding: utf-8 -*-
"""
qudi-core-HiM: message boxes shown by the tasks. A task runs in its own thread, a message box must be
created in the GUI thread: both functions hand the box over to a QObject living in the application
thread through a queued signal, so they can be called from the task thread.

  - show_warning_popup(title, text): non-modal warning box, the task does not wait (used by the
    fluidics steps, e.g. needle position not defined).
  - show_info_popup(title, text): the same with an information icon (e.g. the Hi-M experiment stopped by the
    autofocus check); the task does not wait, the box stays open until it is closed.
  - ask_confirmation(task, title, text, ok_text): modal box with ok_text and Cancel, built by
    build_confirmation_box of the Task Runner (gui/task_runner/dialogs.py, same dialog as the
    start_warning of a task); the task thread waits for the answer and stays interruptible (used by the
    ROI scan on the spinning disk, ZEN settings check).

Without a GUI (no QApplication with widgets) nothing is shown.

Modified with Claude code (Anthropic)

-----------------------------------------------------------------------------------
qudi-core is free software: you can redistribute it and/or modify it under the terms of the GNU General Public License
as published by the Free Software Foundation, either version 3 of the License, or (at your option) any later version.

Qudi is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU General Public License for more details.

You should have received a copy of the GNU General Public License along with Qudi. If not, see <http://www.gnu.org/licenses/>.
-----------------------------------------------------------------------------------
"""

__all__ = ['show_warning_popup', 'show_info_popup', 'ask_confirmation']

import itertools
import threading

from qtpy import QtCore, QtWidgets

from qudi.gui.task_runner.dialogs import build_confirmation_box, is_confirmed

_POLL_S = 0.1  # maximum time between two interrupt checks while waiting for an answer


def _gui_app():
    """The QApplication if there is a GUI (widgets), else None."""
    app = QtWidgets.QApplication.instance()
    return app if isinstance(app, QtWidgets.QApplication) else None


def _in_gui_thread(obj, app):
    if obj.thread() is not app.thread():
        obj.moveToThread(app.thread())
    return obj


# ======================================================================================================================
# Non-modal warning
# ======================================================================================================================

class _WarningPopup(QtCore.QObject):
    """Shows non-modal message boxes (warning icon, or information icon with info=True) in the GUI thread; show()
    may be called from a task thread. The boxes are kept referenced until they are closed."""
    _sigShow = QtCore.Signal(str, str, bool)

    def __init__(self):
        super().__init__()
        self._boxes = []
        self._sigShow.connect(self._show_box)

    def show(self, title, text, info=False):
        self._sigShow.emit(title, text, bool(info))

    @QtCore.Slot(str, str, bool)
    def _show_box(self, title, text, info=False):
        icon = QtWidgets.QMessageBox.Information if info else QtWidgets.QMessageBox.Warning
        box = QtWidgets.QMessageBox(icon, title, text, QtWidgets.QMessageBox.Ok)
        box.setModal(False)
        box.finished.connect(lambda _result, b=box: self._boxes.remove(b) if b in self._boxes else None)
        self._boxes.append(box)
        box.show()


_warning_popup = None


def show_warning_popup(title, text):
    """Show a non-modal warning message box in the GUI thread. Returns False (nothing shown) without a GUI."""
    global _warning_popup
    app = _gui_app()
    if app is None:
        return False
    if _warning_popup is None:
        _warning_popup = _in_gui_thread(_WarningPopup(), app)
    _warning_popup.show(title, text)
    return True


def show_info_popup(title, text):
    """Show a non-modal information message box in the GUI thread (the calling thread does not wait). Returns
    False (nothing shown) without a GUI."""
    global _warning_popup
    app = _gui_app()
    if app is None:
        return False
    if _warning_popup is None:
        _warning_popup = _in_gui_thread(_WarningPopup(), app)
    _warning_popup.show(title, text, info=True)
    return True


# ======================================================================================================================
# Modal confirmation
# ======================================================================================================================

class _ConfirmPopup(QtCore.QObject):
    """Shows modal confirmation boxes in the GUI thread. Each request has an id; the answer (True for
    the ok button, False for Cancel or a closed window) is stored with a threading.Event that the
    task thread waits on."""
    _sigAsk = QtCore.Signal(int, str, str, str)
    _sigClose = QtCore.Signal(int)

    def __init__(self):
        super().__init__()
        self._boxes = {}     # request id -> QMessageBox
        self._answers = {}   # request id -> [threading.Event, bool]
        self._ids = itertools.count(1)
        self._lock = threading.Lock()
        self._sigAsk.connect(self._show_box)
        self._sigClose.connect(self._close_box)

    def request(self, title, text, ok_text):
        """Ask for a box (any thread). Returns (request id, event set when answered, answer holder)."""
        with self._lock:
            request_id = next(self._ids)
            holder = [threading.Event(), False]
            self._answers[request_id] = holder
        self._sigAsk.emit(request_id, title, text, ok_text)
        return request_id, holder

    def close(self, request_id):
        """Close the box of a request without an answer (any thread)."""
        self._sigClose.emit(request_id)

    @QtCore.Slot(int, str, str, str)
    def _show_box(self, request_id, title, text, ok_text):
        with self._lock:
            if request_id not in self._answers:  # closed before it was shown
                return
        # same dialog as the start_warning of a task: Escape and the window close button answer Cancel
        box, ok_button = build_confirmation_box(QtWidgets.QApplication.activeWindow(), title, text, ok_text)
        box.finished.connect(
            lambda _result, i=request_id, b=box, o=ok_button: self._answered(i, is_confirmed(b, o)))
        self._boxes[request_id] = box
        box.show()

    def _answered(self, request_id, ok):
        box = self._boxes.pop(request_id, None)
        if box is not None:
            box.deleteLater()
        with self._lock:
            holder = self._answers.pop(request_id, None)
        if holder is not None:
            holder[1] = bool(ok)
            holder[0].set()

    @QtCore.Slot(int)
    def _close_box(self, request_id):
        with self._lock:
            self._answers.pop(request_id, None)
        box = self._boxes.pop(request_id, None)
        if box is not None:
            box.close()
            box.deleteLater()


_confirm_popup = None


def ask_confirmation(task, title, text, ok_text='Done - continue') -> bool:
    """Show a modal box (build_confirmation_box) with the buttons ok_text and Cancel in the GUI thread and wait
    for the answer, calling task._check_interrupt() at least every 0.1 s; an interrupt closes the box and
    raises as usual. Returns True for ok_text, False for Cancel or a closed window.
    Without a GUI: logs the text at warning level and returns True."""
    global _confirm_popup
    app = _gui_app()
    if app is None:
        task.log.warning(f'{title}: {text}')
        return True
    if _confirm_popup is None:
        _confirm_popup = _in_gui_thread(_ConfirmPopup(), app)
    request_id, holder = _confirm_popup.request(title, text, ok_text)
    in_gui_thread = QtCore.QThread.currentThread() is app.thread()
    try:
        while not holder[0].is_set():
            task._check_interrupt()
            if in_gui_thread:
                # called from the GUI thread itself: keep its events running while waiting
                app.processEvents(QtCore.QEventLoop.AllEvents, int(_POLL_S * 1000))
                holder[0].wait(0.01)
            else:
                holder[0].wait(_POLL_S)
    except BaseException:
        _confirm_popup.close(request_id)
        raise
    return holder[1]
