# -*- coding: utf-8 -*-

"""
This file contains scripts for testing the qudi.core.scripting package.

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

Modified for qudi-core-HiM (2026-09-24, Modified with Claude code): removed a non-functional
  interrupt_task(name) method that had been added directly to TestTask - it referenced
  self._running_tasks / self._thread_lock, which belong to TaskRunnerLogic, not to a ModuleTask, so
  it would have raised AttributeError if it were ever called (it wasn't - nothing in the GUI or
  taskrunner calls a task by that name). The actual, correct abort mechanism (self._check_interrupt()
  / self._interruptible_sleep(), triggered by TaskRunnerLogic.interrupt_task -> self.interrupt()) was
  already implemented correctly in _run() and is documented on the TestTask class docstring below.
  Also added log messages so an abort is visible in the log console (interrupt flag detected,
  cleanup running).
"""

from typing import Iterable, Sequence, Mapping, Union, Any, Optional, Tuple

from time import monotonic, sleep

from qudi.core.scripting.moduletask import ModuleTask
from qudi.core.connector import Connector


class TestTask(ModuleTask):
    """Minimal fluidics task (one valve, three positions) used to validate that a ModuleTask can be
    started and cleanly aborted from the Task Runner GUI.

    Abort / interrupt, how it actually works in qudi-core (different from the legacy qudi task
    model): there is no per-task "interrupt_task" method to define - a task cannot be interrupted
    from the outside by force. Clicking the stop button in the Task Runner GUI calls
    TaskRunnerLogic.interrupt_task(name) (see taskrunner_logic.py), which simply calls this task's
    inherited self.interrupt() - that only sets a thread-safe flag, it does not touch the running
    _run() call in any way. It is this task's own responsibility to notice that flag by calling
    self._check_interrupt() regularly from within _run() (it raises ModuleScriptInterrupted, which
    the base class catches to stop the task and run _cleanup()). Long blocking hardware calls
    between two checks (or a wait implemented with a single sleep() instead of
    _interruptible_sleep(), see below) cannot be interrupted while they are running - so every real
    task must be written with frequent-enough checkpoints, not just this test one.
    """
    valve = Connector(name='fluidics_valve', interface='FluidicsValveLogic')
    # robot = Connector(name='pipetting_robot', interface='FluidicsRobotLogic')
    # flow = Connector(name='fluidics_flow', interface='FluidicsFlowLogic')

    def _setup(self) -> None:
        self._valve = self.valve()
        # self._robot = self.robot()
        # self._flow = self.flow()

    def _run(self, delay_s: float = 5.0) -> dict:
        self._check_interrupt()
        self.log.info("Change position valve a to 2")
        self._valve.set_valve_position("a", 2)
        self._interruptible_sleep(delay_s)

        self._check_interrupt()
        self.log.info("Change position valve a to 3")
        self._valve.set_valve_position("a", 3)
        self._interruptible_sleep(delay_s)

        self._check_interrupt()
        self.log.info("Change position valve a to 1")
        self._valve.set_valve_position("a", 1)

    def _cleanup(self) -> None:
        """Return the valve to a safe position. Called unconditionally by the base class once _run
        finishes, raises, or is interrupted - including after an abort from the GUI.
        """
        self.log.info("TestTask: cleanup running (valve -> safe position).")
        valve = getattr(self, "_valve", None)
        if valve is not None:
            valve.set_valve_position("a", 1)
        self.log.info("Valve test cleanup completed.")

    def _interruptible_sleep(self, duration_s: float, poll_interval_s: float = 0.1,) -> None:
        """Wait while checking regularly for an interruption."""
        deadline = monotonic() + duration_s

        while True:
            if self.interrupted:
                self.log.info("TestTask: interrupt flag detected, aborting the current step.")
            self._check_interrupt()
            remaining_s = deadline - monotonic()
            if remaining_s <= 0:
                return
            sleep(min(poll_interval_s, remaining_s))


class TestTask2(ModuleTask):

    _robot = Connector(name='pipetting_robot_logic', interface='LogicBase')
    _valve = Connector(name='valve_logic', interface='LogicBase')
    _flow = Connector(name='flowcontrol_logic', interface='LogicBase')

    def _setup(self) -> None:
        i = 0
        for i in range(100000000):
            i += 1

    def _cleanup(self) -> None:
        i = 0
        for i in range(100000000):
            i += 1

    def _run(self, seq_arg: Sequence[int], iter_arg: Iterable[str], map_arg: Mapping[str, int],
             opt_arg: Optional[int] = 42
             ) -> Tuple[Sequence[int], Iterable[str], Mapping[str, int], int]:
        i = 0
        for i in range(10000000):
            if i % 100 == 0:
                self._check_interrupt()
            i += 1
        return seq_arg, iter_arg, map_arg, opt_arg