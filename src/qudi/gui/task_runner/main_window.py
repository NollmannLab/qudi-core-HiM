# -*- coding: utf-8 -*-
"""
This file contains the QMainWindow class for the task GUI.

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

Modified for qudi-core-HiM (2026-10-08, Modified with Claude code): compact layout. Task group
  boxes used to expand to share all the spare window height (no stretch at the end of
  tasks_layout) and used a bold title enlarged by 2 pt that was inherited by every label and editor
  inside. A stretch now closes tasks_layout so the tasks pack at the top (the QScrollArea is kept
  for setups with very many tasks), new group boxes are inserted before that stretch, the group box
  title is bold at normal size while its contents keep the normal (non-bold) font, and contents
  margins/spacing are tight. Signals, slots and _clear_task_widgets are unchanged.
"""

import os
from typing import Any, Mapping, Dict, Type, Callable
from qtpy import QtCore, QtGui, QtWidgets

from qudi.util.paths import get_artwork_dir
from qudi.core.scripting.moduletask import ModuleTask

from .taskwidget import TaskWidget


class TaskMainWindow(QtWidgets.QMainWindow):
    """
    Main Window definition for the task GUI.
    """

    sigStartTask = QtCore.Signal(str, dict)  # task name, call parameters
    sigInterruptTask = QtCore.Signal(str)  # task name
    sigClosed = QtCore.Signal()

    def __init__(self, *args, tasks: Mapping[str, Type[ModuleTask]], **kwargs):
        super().__init__(*args, **kwargs)

        self.setWindowTitle('qudi: Taskrunner')

        # Create actions
        icon_path = os.path.join(get_artwork_dir(), 'icons')
        self.action_quit = QtWidgets.QAction()
        self.action_quit.setIcon(QtGui.QIcon(os.path.join(icon_path, 'application-exit')))
        self.action_quit.setText('Close')
        self.action_quit.setToolTip('Close')
        self.action_quit.triggered.connect(self.close)

        # Create menu bar
        self.menubar = QtWidgets.QMenuBar()
        menu = QtWidgets.QMenu('File')
        menu.addAction(self.action_quit)
        self.menubar.addMenu(menu)
        self.setMenuBar(self.menubar)

        # Create central container widget for ModuleTask widgets
        # self.scroll_area = QtWidgets.QScrollArea()
        self.task_widgets = dict()
        self.tasks_layout = QtWidgets.QVBoxLayout()
        self.tasks_layout.setContentsMargins(6, 6, 6, 6)
        self.tasks_layout.setSpacing(4)
        # Trailing stretch packs the task group boxes at the top of the window. Group boxes are
        # inserted before it (see _initialize_task_widgets).
        self.tasks_layout.addStretch(1)
        widget = QtWidgets.QWidget()
        widget.setLayout(self.tasks_layout)
        scroll_area = QtWidgets.QScrollArea()
        scroll_area.setWidget(widget)
        scroll_area.setWidgetResizable(True)
        self.setCentralWidget(scroll_area)

        self._initialize_task_widgets(tasks)

        # # Create toolbar
        # self.toolbar = QtWidgets.QToolBar()
        # self.toolbar.setOrientation(QtCore.Qt.Horizontal)
        # self.toolbar.addAction(self.action_start_task)
        # self.toolbar.addAction(self.action_pause_task)
        # self.toolbar.addAction(self.action_stop_task)
        # self.addToolBar(self.toolbar)

    def closeEvent(self, event: QtGui.QCloseEvent) -> None:
        super().closeEvent(event)
        self.sigClosed.emit()

    @QtCore.Slot(str)
    def task_started(self, name: str) -> None:
        self.task_widgets[name].task_started()

    @QtCore.Slot(str, str)
    def task_state_changed(self, name: str, state: str) -> None:
        self.task_widgets[name].task_state_changed(state)

    @QtCore.Slot(str, object, bool)
    def task_finished(self, name: str, result: Any, success: bool) -> None:
        self.task_widgets[name].task_finished(result, success)

    def _initialize_task_widgets(self, tasks: Mapping[str, Type[ModuleTask]]) -> None:
        for ii, (task_name, task_type) in enumerate(tasks.items()):
            groupbox = QtWidgets.QGroupBox(task_name)
            font = groupbox.font()
            font.setBold(True)
            groupbox.setFont(font)
            widget = TaskWidget(task_type=task_type)
            # Only the group box title is bold; parameter labels/editors keep the normal font
            content_font = QtGui.QFont(font)
            content_font.setBold(False)
            widget.setFont(content_font)
            layout = QtWidgets.QVBoxLayout()
            layout.setContentsMargins(6, 2, 6, 4)
            layout.setSpacing(0)
            layout.addWidget(widget)
            groupbox.setLayout(layout)
            groupbox.setSizePolicy(QtWidgets.QSizePolicy.Preferred, QtWidgets.QSizePolicy.Maximum)
            widget.sigStartTask.connect(self._get_start_task_callback(task_name))
            widget.sigInterruptTask.connect(self._get_interrupt_task_callback(task_name))
            # Insert before the trailing stretch so tasks stay packed at the top
            self.tasks_layout.insertWidget(self.tasks_layout.count() - 1, groupbox)
            self.task_widgets[task_name] = widget

    def _clear_task_widgets(self) -> None:
        """Helper method to disconnect and delete all TaskWidgets and remove them from layout.
        """
        for widget in reversed(self.task_widgets):
            groupbox = widget.parent()
            widget.sigStartTask.disconnect()
            widget.sigInterruptTask.disconnect()
            self.tasks_layout.removeWidget(groupbox)
            groupbox.setParent(None)
            groupbox.deleteLater()
        self.task_widgets = dict()

    def _get_start_task_callback(self, task_name: str) -> Callable[[Dict[str, Any]], None]:

        def callback(parameters: Dict[str, Any]) -> None:
            self.sigStartTask.emit(task_name, parameters)

        return callback

    def _get_interrupt_task_callback(self, task_name: str) -> Callable[[], None]:

        def callback() -> None:
            self.sigInterruptTask.emit(task_name)

        return callback
