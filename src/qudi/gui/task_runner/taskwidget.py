# -*- coding: utf-8 -*-
"""
This file contains a widget to control a ModuleTask and display its state.

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

Modified for qudi-core-HiM (2026-10-08, Modified with Claude code): compact layout. Each task used
  far more vertical space than its 0-1 parameters needed (run/stop button was a square of twice the
  state-label width with its icon scaled to fill it, controls were stacked vertically, and the
  parameter grid added row stretch / minimum row heights). The widget is now a single horizontal
  row "[parameters] | [state label] [busy indicator] [run/stop button]": parameters are laid out
  row-major, at most 3 label/editor pairs per line by default (wrapping onto extra lines), and the
  controls stay on the first line, top-right. The run/stop button is a normal QToolButton of
  standard line height with a 16-24 px icon, the busy indicator is the same size and still retains
  its space when hidden, and the state label has a fixed minimum width for the longest state text
  so the controls do not shift. The unused TestToolButton class (it rescaled its icon to the button
  size) was removed. The meaning of "max_columns" / "max_rows" changed accordingly - see the
  TaskWidget docstring. Signals, slots and the start/interrupt logic are unchanged.

Modified for qudi-core-HiM (2026-10-08, Modified with Claude code): optional start confirmation
  and end reminder declared by the task. Some tasks need a manual hardware step before they start
  and after they end (e.g. photobleaching.py: unplug, then re-plug, the Celesta shutter TTL
  cable). A ModuleTask can now define the class attributes "start_warning" / "end_warning" (plain
  strings). When Run is clicked, start_warning is shown in a modal dialog that must be confirmed
  ("Done - start task"; Cancel/Esc/close aborts the start). When a task that this widget saw start
  finishes (success, failure or interrupt), end_warning is shown in a non-modal reminder. The
  initialising task_finished() call made by TaskRunnerGui.on_activate does not show it. Both
  events are logged at info level. Dialogs are opened here, in the GUI thread - never from the
  task, which runs in a worker thread. Tasks without these attributes behave exactly as before.
  New optional constructor argument "task_name" (configured display name, used in dialog titles
  and log messages; defaults to the task class name).
"""

__all__ = ['TaskWidget']

import math
import os
from typing import Type, Optional, Dict, Tuple, Any, Iterable
from qtpy import QtCore, QtWidgets, QtGui

from qudi.util.helpers import is_integer
from qudi.util.paths import get_artwork_dir
from qudi.util.parameters import ParameterWidgetMapper
from qudi.util.widgets.loading_indicator import CircleLoadingIndicator
from qudi.util.widgets.separator_lines import VerticalLine
from qudi.core.logger import get_logger
from qudi.core.scripting.moduletask import ModuleTask

_log = get_logger(__name__)


class TaskWidget(QtWidgets.QWidget):
    """QWidget to control a ModuleTask and display its state.

    Layout: a single horizontal row "[parameters] | [state label] [busy indicator] [run/stop]".
    Parameter label/editor pairs are placed row-major in a grid and wrap onto further lines once a
    line holds the maximum number of pairs; the controls stay right-aligned on the first line.

    @param task_type: ModuleTask subclass whose call parameters get an editor each
    @param max_columns: maximum number of label/editor PAIRS per line (default 3 when neither
                        argument is given)
    @param max_rows: alternatively, maximum number of lines; the number of pairs per line is then
                     chosen as ceil(number_of_parameters / max_rows)
    Only one of max_columns / max_rows may be given. (Before 2026-10-08 the grid was filled
    column-major and max_rows defaulted to 8.)
    @param task_name: display name of the task (as configured), used in dialog titles and log
                      messages; defaults to the task class name

    Optional task class attributes (opt-in, read with getattr; absent or empty = no dialog):
        start_warning (str): shown in a modal confirmation dialog every time Run is clicked. The
                             task only starts if the user clicks "Done — start task"; Cancel,
                             Esc or closing the dialog aborts the start (nothing is emitted).
                             Never shown when the button is used to interrupt a running task.
        end_warning (str): shown in a non-modal reminder when a task that this widget saw start
                           finishes, whether it succeeded, failed or was interrupted.
    Both are plain class attributes of the ModuleTask (e.g. PhotoBleachingSDTask), because task
    config options are not passed to ModuleTasks. Dialogs are always opened here, in the GUI
    thread, never from the task itself (tasks run in a worker thread).
    """

    sigStartTask = QtCore.Signal(dict)  # parameters
    sigInterruptTask = QtCore.Signal()

    _ParamWidgetsIterable = Iterable[Tuple[QtWidgets.QLabel, QtWidgets.QWidget]]
    _ParamWidgetsDict = Dict[str, Tuple[QtWidgets.QLabel, QtWidgets.QWidget]]

    _DEFAULT_PAIRS_PER_LINE = 3
    # Every text the state label may show (ModuleTask state machine + spare entries); the label is
    # given a minimum width that fits the longest one so the controls never shift.
    _STATE_TEXTS = ('stopped', 'starting', 'running', 'finishing', 'paused', 'pausing',
                    'resuming')

    def __init__(self, *args, task_type: Type[ModuleTask], max_columns: Optional[int] = None,
                 max_rows: Optional[int] = None, task_name: Optional[str] = None, **kwargs):
        super().__init__(*args, **kwargs)

        # Optional texts declared by the task (see class docstring)
        self._task_name = task_name if task_name else task_type.__name__
        self._start_warning = getattr(task_type, 'start_warning', None) or None
        self._end_warning = getattr(task_type, 'end_warning', None) or None
        # True once this widget has seen the task start; gates the end reminder so that the
        # initialising task_finished() call from TaskRunnerGui.on_activate shows nothing.
        self._started_since_reminder = False
        self._end_reminder_box = None  # keeps the non-modal reminder referenced while open

        if max_rows is not None and max_columns is not None:
            raise ValueError('Can either set "max_columns" OR "max_rows" but not both.')
        if max_columns is not None and not is_integer(max_columns):
            raise ValueError('"max_columns" must be None or integer value')
        if max_rows is not None and not is_integer(max_rows):
            raise ValueError('"max_rows" must be None or integer value')

        number_of_widgets = len(task_type.call_parameters())
        if max_columns is not None:
            pairs_per_line = max(1, int(max_columns))
        elif max_rows is not None:
            pairs_per_line = max(1, math.ceil(number_of_widgets / max(1, int(max_rows))))
        else:
            pairs_per_line = self._DEFAULT_PAIRS_PER_LINE

        # Standard line height (as of a spinbox) used to size the compact controls
        line_height = QtWidgets.QSpinBox().sizeHint().height()
        icon_size = max(16, min(24, line_height - 6))

        # Create control button and state label. Arrange them in a sub-layout and connect button.
        # Also add animated busy-indicator
        icon_dir = os.path.join(get_artwork_dir(), 'icons')
        self._play_icon = QtGui.QIcon(os.path.join(icon_dir, 'media-playback-start'))
        self._stop_icon = QtGui.QIcon(os.path.join(icon_dir, 'media-playback-stop'))
        self.state_label = QtWidgets.QLabel('stopped')
        self.state_label.setAlignment(QtCore.Qt.AlignCenter)
        font = self.state_label.font()
        font.setBold(True)
        self.state_label.setFont(font)
        metrics = QtGui.QFontMetrics(font)
        self.state_label.setMinimumWidth(
            max(metrics.horizontalAdvance(text) for text in self._STATE_TEXTS) + 8
        )
        self.run_interrupt_button = QtWidgets.QToolButton()
        self.run_interrupt_button.setIcon(self._play_icon)
        self.run_interrupt_button.setToolButtonStyle(QtCore.Qt.ToolButtonIconOnly)
        self.run_interrupt_button.setIconSize(QtCore.QSize(icon_size, icon_size))
        self.run_interrupt_button.setFixedSize(line_height, line_height)

        self.running_indicator = CircleLoadingIndicator()
        self.running_indicator.setFixedSize(line_height, line_height)
        tmp = self.running_indicator.sizePolicy()
        tmp.setRetainSizeWhenHidden(True)
        self.running_indicator.setSizePolicy(tmp)
        self.running_indicator.hide()

        ctrl_widget = QtWidgets.QWidget()
        ctrl_layout = QtWidgets.QHBoxLayout()
        ctrl_layout.setContentsMargins(0, 0, 0, 0)
        ctrl_layout.setSpacing(4)
        ctrl_layout.addWidget(self.state_label)
        ctrl_layout.addWidget(self.running_indicator)
        ctrl_layout.addWidget(self.run_interrupt_button)
        ctrl_widget.setLayout(ctrl_layout)
        ctrl_widget.setSizePolicy(QtWidgets.QSizePolicy.Fixed, QtWidgets.QSizePolicy.Fixed)

        self.run_interrupt_button.clicked.connect(self._run_interrupt_clicked)

        # Create task parameter editors and put them in a sub-layout
        self.parameter_widgets = self.__create_parameter_editor_widgets(task_type)

        # Add sub-layouts to main layout: parameters take the remaining width, controls are
        # right-aligned on the first line. A task without parameters only shows the controls.
        main_layout = QtWidgets.QHBoxLayout()
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(6)
        if self.parameter_widgets:
            param_layout = self.__layout_parameter_widgets(self.parameter_widgets.values(),
                                                           pairs_per_line)
            main_layout.addLayout(param_layout, 1)
            main_layout.addWidget(VerticalLine())
        else:
            main_layout.addStretch(1)
        main_layout.addWidget(ctrl_widget, 0, QtCore.Qt.AlignTop | QtCore.Qt.AlignRight)
        self.setLayout(main_layout)
        self.setSizePolicy(QtWidgets.QSizePolicy.Preferred, QtWidgets.QSizePolicy.Maximum)

        # State flag to indicate current button functionality (start or interrupt)
        self._interrupt_enabled = False

    @staticmethod
    def __create_parameter_editor_widgets(task_type: Type[ModuleTask]) -> _ParamWidgetsDict:
        """Helper function to create editor widgets and labels for each ModuleTask call parameter.
        """
        task_parameters = task_type.call_parameters()
        param_widgets = dict()
        for param_name, param in task_parameters.items():
            editor = ParameterWidgetMapper.widget_for_parameter(param)
            if editor is None:
                editor = QtWidgets.QLabel('Unknown parameter type')
                editor.setSizePolicy(QtWidgets.QSizePolicy.Minimum, QtWidgets.QSizePolicy.Minimum)
            else:
                editor = editor()
                # ToDo: Set default values here
            label = QtWidgets.QLabel(f'{param_name}:')
            label.setAlignment(QtCore.Qt.AlignVCenter | QtCore.Qt.AlignRight)
            param_widgets[param_name] = (label, editor)
        return param_widgets

    @staticmethod
    def __layout_parameter_widgets(param_widgets: _ParamWidgetsIterable,
                                   pairs_per_line: int) -> QtWidgets.QGridLayout:
        """Helper function to layout parameter widgets in a QGridLayout, row-major, with at most
        pairs_per_line label/editor pairs per line. Labels keep their natural width, editors share
        the remaining width. No row stretch or minimum row height is added, so each line is only as
        tall as its tallest editor.
        """
        layout = QtWidgets.QGridLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setHorizontalSpacing(6)
        layout.setVerticalSpacing(2)
        for index, (label, editor) in enumerate(param_widgets):
            row, pair = divmod(index, pairs_per_line)
            column = 2 * pair
            layout.addWidget(label, row, column)
            layout.addWidget(editor, row, column + 1)
            layout.setColumnStretch(column + 1, 1)
        return layout

    @QtCore.Slot()
    def _run_interrupt_clicked(self) -> None:
        """Callback method for button clicks."""
        if self._interrupt_enabled:
            self.sigInterruptTask.emit()
        else:
            if self._start_warning and not self._confirm_start_warning():
                _log.info(f'{self._task_name}: start cancelled by the user (start warning not '
                          f'confirmed).')
                return
            self.run_interrupt_button.setEnabled(False)
            self.sigStartTask.emit(self.get_parameters())

    def _confirm_start_warning(self) -> bool:
        """Show the task's start_warning in a modal dialog. Returns True only if the user clicked
        the confirm button; Cancel, Esc or closing the dialog return False.
        """
        box = QtWidgets.QMessageBox(self.window())
        box.setIcon(QtWidgets.QMessageBox.Warning)
        box.setWindowTitle(f'Before starting: {self._task_name}')
        box.setText(self._start_warning)
        confirm_button = box.addButton('Done — start task', QtWidgets.QMessageBox.AcceptRole)
        cancel_button = box.addButton(QtWidgets.QMessageBox.Cancel)
        box.setDefaultButton(cancel_button)
        box.setEscapeButton(cancel_button)
        box.setWindowModality(QtCore.Qt.ApplicationModal)
        box.exec()
        confirmed = box.clickedButton() is confirm_button
        box.deleteLater()
        if confirmed:
            _log.info(f'{self._task_name}: user confirmed start warning: {self._start_warning}')
        return confirmed

    def _show_end_reminder(self) -> None:
        """Show the task's end_warning in a non-modal reminder, so the GUI keeps updating."""
        _log.info(f'{self._task_name}: end reminder shown: {self._end_warning}')
        box = QtWidgets.QMessageBox(self.window())
        box.setIcon(QtWidgets.QMessageBox.Warning)
        box.setWindowTitle(f'Task finished: {self._task_name}')
        box.setText(self._end_warning)
        box.setStandardButtons(QtWidgets.QMessageBox.Ok)
        box.setWindowModality(QtCore.Qt.NonModal)
        box.setAttribute(QtCore.Qt.WA_DeleteOnClose, True)
        box.finished.connect(self._end_reminder_closed)
        self._end_reminder_box = box
        box.show()

    @QtCore.Slot(int)
    def _end_reminder_closed(self, _result: int = 0) -> None:
        self._end_reminder_box = None

    @QtCore.Slot()
    def task_started(self) -> None:
        self._interrupt_enabled = True
        self._started_since_reminder = True
        self.run_interrupt_button.setIcon(self._stop_icon)
        self.run_interrupt_button.setEnabled(True)
        self.running_indicator.show()

    @QtCore.Slot(str)
    def task_state_changed(self, new_state: str) -> None:
        """Callback method for ModuleTask state changes."""
        self.state_label.setText(new_state)

    @QtCore.Slot(object, bool)
    def task_finished(self, result: Any, success: bool) -> None:
        """Callback for task finished event."""
        self._interrupt_enabled = False
        self.run_interrupt_button.setIcon(self._play_icon)
        self.run_interrupt_button.setEnabled(True)
        self.running_indicator.hide()
        self.set_task_result(result, success)
        # End reminder only for a run this widget saw start (not for the initialising call made
        # by TaskRunnerGui.on_activate), whatever the outcome (success, failure, interrupt).
        if self._started_since_reminder:
            self._started_since_reminder = False
            if self._end_warning:
                self._show_end_reminder()

    @QtCore.Slot(object, bool)
    def set_task_result(self, result: Any, success: bool) -> None:
        """Updates the task result display."""
        print(result, success)

    def get_parameters(self) -> Dict[str, Any]:
        """Reads parameters from parameter editors and returns them in a dict."""
        parameters = dict()
        for param_name, (_, editor) in self.parameter_widgets.items():
            if isinstance(editor, QtWidgets.QLabel):
                continue
            try:
                parameters[param_name] = editor.value()
            except AttributeError:
                try:
                    parameters[param_name] = editor.isChecked()
                except AttributeError:
                    parameters[param_name] = editor.text()
        return parameters
