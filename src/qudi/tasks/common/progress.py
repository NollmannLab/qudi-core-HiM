# -*- coding: utf-8 -*-
"""
qudi-core-HiM task base: a ModuleTask that reports what it is doing now to the Task Runner window.

ProgressModuleTask emits sigProgress(step, text), e.g. ('2/5', 'Injecting WB - 120/200 µl').
TaskRunnerLogic forwards it as sigTaskProgress(name, step, text) and the Task Runner window shows
"<step> - <text>" under the controls of the running task. Tasks deriving from ModuleTask directly
emit nothing and are displayed as before.

Modified with Claude code (Anthropic)

-----------------------------------------------------------------------------------
qudi-core is free software: you can redistribute it and/or modify it under the terms of the GNU General Public License
as published by the Free Software Foundation, either version 3 of the License, or (at your option) any later version.

Qudi is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU General Public License for more details.

You should have received a copy of the GNU General Public License along with Qudi. If not, see <http://www.gnu.org/licenses/>.
-----------------------------------------------------------------------------------
"""

from time import monotonic

from qtpy import QtCore
from qudi.core.scripting.moduletask import ModuleTask


class ProgressModuleTask(ModuleTask):
    """ModuleTask that reports its progress (a ModuleTask subclass: Qt signals must be declared on a
    QObject class).

    sigProgress(step, text): step, e.g. '2/5'; text, e.g. 'Injecting WB - 120/200 µl'.
    _report_progress(step, text): emit now and log "<step> - <text>" (at each new step).
    _report_live(step, text): emit at most once every progress_interval_s, no log line (inside
        waiting loops). An update that comes too early is dropped, not queued.
    The only value kept is the time of the last emission, used by _report_live.
    """

    sigProgress = QtCore.Signal(str, str)  # step ("2/5"), text ("Injecting WB - 120/200 µl")

    progress_interval_s = 1.0

    _last_progress_emit = None  # monotonic time of the last emission (instance attribute once set)

    def _report_progress(self, step: str, text: str, log: bool = True) -> None:
        """Emit the progress now. log=False when the caller already logs the same information."""
        self._last_progress_emit = monotonic()
        self.sigProgress.emit(str(step), str(text))
        if log:
            self.log.info(f'{step} - {text}')

    def _report_live(self, step: str, text: str) -> None:
        """Emit the progress if progress_interval_s has passed since the last emission; otherwise
        drop it. Nothing is logged."""
        now = monotonic()
        if self._last_progress_emit is not None and now - self._last_progress_emit < self.progress_interval_s:
            return
        self._last_progress_emit = now
        self.sigProgress.emit(str(step), str(text))
