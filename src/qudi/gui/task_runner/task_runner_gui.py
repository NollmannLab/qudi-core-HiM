# -*- coding: utf-8 -*-
"""
This file contains the qudi task runner GUI.

Copyright (c) 2021, the qudi developers. See the AUTHORS.md file at the top-level directory of this
distribution and on <https://github.com/Ulm-IQO/qudi-core/>

This file is part of qudi.

Qudi is free software: you can redistribute it and/or modify it under the terms of
the GNU Lesser General Public License as published by the Free Software Foundation,
either version 3 of the License, or (at your option) any later version.

Qudi is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY;
without even the implied warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.
See the GNU Lesser General Public License for more details.

You should have received a copy of the GNU Lesser General Public License along with qudi.
If not, see <https://www.gnu.org/licenses/>.

Modified for qudi-core-HiM (2026-09-25, Modified with Claude code): the interrupt (abort) button in
  the Task Runner GUI had no effect on real hardware - a click was only ever processed by
  TaskRunnerLogic.interrupt_task once the running task had already finished on its own, regardless
  of when the button was clicked (confirmed on the dummy fluidics task: the "Interrupt requested"
  log line always carried the same, late timestamp no matter when the click happened). Changed the
  sigInterruptTask connection from QueuedConnection to DirectConnection - see the comment at that
  line for why this is safe (interrupt_task only touches already-locked state). taskrunner_logic.py
  and tasks/dummy_fluidics_task.py were not the source of this particular issue (their cooperative
  interrupt / _check_interrupt logic already matches qudi-core 1.7.0 exactly) but were fixed
  separately in the previous round (removed a non-functional interrupt_task method, added logging).
"""

#from PySide6 import QtCore
from qtpy import QtCore
from qudi.core.connector import Connector
from qudi.core.module import GuiBase

from .main_window import TaskMainWindow


class TaskRunnerGui(GuiBase):
    """
    TODO: Document
    """

    # declare connectors
    _task_runner = Connector(name='task_runner', interface='TaskRunnerLogic')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._mw = None

    def on_activate(self):
        """Create all UI objects and show the window.
        """
        # Initialize main window and connect task widgets
        taskrunner = self._task_runner()
        self._mw = TaskMainWindow(tasks=taskrunner.configured_task_types)
        self._mw.sigStartTask.connect(taskrunner.run_task, QtCore.Qt.QueuedConnection)
        # Interrupt is intentionally a DIRECT connection, not queued: TaskRunnerLogic.interrupt_task
        # only ever touches state that is already protected by a lock (its own _running_tasks dict,
        # and the task's own interrupt flag), so there is no need to marshal the call through
        # TaskRunnerLogic's thread event queue - and on real hardware that queue was observed to sit
        # behind the running task's own thread for its entire duration (an abort click was only ever
        # processed once the task had already finished on its own), so the click never actually
        # reached interrupt_task in time to have any effect. A direct call takes effect immediately,
        # from whichever thread the click happened on, regardless of what TaskRunnerLogic's own
        # thread is doing.
        self._mw.sigInterruptTask.connect(taskrunner.interrupt_task, QtCore.Qt.DirectConnection)
        self._mw.sigClosed.connect(self._deactivate_self)
        taskrunner.sigTaskStarted.connect(self._mw.task_started, QtCore.Qt.QueuedConnection)
        taskrunner.sigTaskStateChanged.connect(self._mw.task_state_changed,
                                               QtCore.Qt.QueuedConnection)
        taskrunner.sigTaskFinished.connect(self._mw.task_finished, QtCore.Qt.QueuedConnection)

        # Set current task states
        for task_name, task_state in taskrunner.task_states.items():
            if task_state != 'stopped':
                self._mw.task_started(task_name)
            else:
                self._mw.task_finished(task_name, None, False)
            self._mw.task_state_changed(task_name, task_state)
        # ToDo: Also set task results here

        self._restore_window_geometry(self._mw)
        self.show()

    def show(self):
        """Make sure that the window is visible and at the top.
        """
        self._mw.show()

    @QtCore.Slot()
    def _deactivate_self(self):
        self._qudi_main.module_manager.deactivate_module(self._meta['name'])

    def on_deactivate(self):
        """Hide window and stop ipython console.
        """
        self._save_window_geometry(self._mw)
        self._mw.close()
        self._mw.sigStartTask.disconnect()
        self._mw.sigInterruptTask.disconnect()
        self._mw.sigClosed.disconnect()
        taskrunner = self._task_runner()
        taskrunner.sigTaskStarted.disconnect(self._mw.task_started, QtCore.Qt.QueuedConnection)
        taskrunner.sigTaskStateChanged.disconnect(self._mw.task_state_changed,
                                               QtCore.Qt.QueuedConnection)
        taskrunner.sigTaskFinished.disconnect(self._mw.task_finished, QtCore.Qt.QueuedConnection)
        self._mw = None
