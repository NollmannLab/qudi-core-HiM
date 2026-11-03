# -*- coding: utf-8 -*-
"""
qudi-core-HiM: dialogs of the Task Runner, shared with the tasks (tasks/common/popups.py).

  - build_confirmation_box(parent, title, text, ok_text): modal question with the buttons ok_text and
    Cancel (Cancel is the default and the Escape button; closing the window answers Cancel). Used for
    the start_warning of a task (taskwidget.py) and for the questions a task asks while it runs
    (ask_confirmation).
  - build_reminder_box(parent, title, text): non-modal reminder with an OK button, deleted when closed
    (end_warning of a task).

The boxes are only built here; the caller shows them (exec() or show()) in the GUI thread.

Modified with Claude code (Anthropic)

-----------------------------------------------------------------------------------
qudi-core is free software: you can redistribute it and/or modify it under the terms of the GNU General Public License
as published by the Free Software Foundation, either version 3 of the License, or (at your option) any later version.

Qudi is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU General Public License for more details.

You should have received a copy of the GNU General Public License along with Qudi. If not, see <http://www.gnu.org/licenses/>.
-----------------------------------------------------------------------------------
"""

__all__ = ['build_confirmation_box', 'build_reminder_box', 'is_confirmed']

from qtpy import QtCore, QtWidgets


def build_confirmation_box(parent, title, text, ok_text):
    """Modal question (warning icon) with the buttons ok_text and Cancel. Cancel is the default and the
    Escape button, so Escape and closing the window answer Cancel. Returns (box, ok_button); after the
    box is finished, is_confirmed(box, ok_button) tells whether ok_text was clicked."""
    box = QtWidgets.QMessageBox(parent)
    box.setIcon(QtWidgets.QMessageBox.Warning)
    box.setWindowTitle(title)
    box.setText(text)
    ok_button = box.addButton(ok_text, QtWidgets.QMessageBox.AcceptRole)
    cancel_button = box.addButton(QtWidgets.QMessageBox.Cancel)
    box.setDefaultButton(cancel_button)
    box.setEscapeButton(cancel_button)
    box.setWindowModality(QtCore.Qt.ApplicationModal)
    return box, ok_button


def is_confirmed(box, ok_button) -> bool:
    """True if the button clicked to finish the box is ok_button."""
    return box.clickedButton() is ok_button


def build_reminder_box(parent, title, text):
    """Non-modal reminder (warning icon) with an OK button, deleted when closed."""
    box = QtWidgets.QMessageBox(parent)
    box.setIcon(QtWidgets.QMessageBox.Warning)
    box.setWindowTitle(title)
    box.setText(text)
    box.setStandardButtons(QtWidgets.QMessageBox.Ok)
    box.setWindowModality(QtCore.Qt.NonModal)
    box.setAttribute(QtCore.Qt.WA_DeleteOnClose, True)
    return box
