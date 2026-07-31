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
"""

from typing import Iterable, Sequence, Mapping, Union, Any, Optional, Tuple

from time import monotonic, sleep

from qudi.core.scripting.moduletask import ModuleTask
from qudi.core.connector import Connector
from qtpy import QtCore

class TestTask(ModuleTask):
    valve = Connector(name='fluidics_valve', interface='FluidicsValveLogic')
    # robot = Connector(name='pipetting_robot', interface='FluidicsRobotLogic')
    # flow = Connector(name='fluidics_flow', interface='FluidicsFlowLogic')

    def _setup(self) -> None:
        self._valve = self.valve()
        # self._robot = self.robot()
        # self._flow = self.flow()

    def _run(self, delay_s: float = 5.0) -> dict:
        self._check_interrupt()
        self._valve.set_valve_position("a", 2)
        self._interruptible_sleep(delay_s)

        self._check_interrupt()
        self._valve.set_valve_position("a", 3)
        self._interruptible_sleep(delay_s)

        self._check_interrupt()
        self._valve.set_valve_position("a", 1)

    def _cleanup(self) -> None:
        """Return the valve to a safe position."""
        valve = getattr(self, "_valve", None)
        if valve is not None:
            valve.set_valve_position("a", 1)
        self.log.info("Valve test cleanup completed.")

    def _interruptible_sleep(self, duration_s: float, poll_interval_s: float = 0.1,) -> None:
        """Wait while checking regularly for an interruption."""
        deadline = monotonic() + duration_s

        while True:
            self._check_interrupt()
            remaining_s = deadline - monotonic()
            if remaining_s <= 0:
                return
            sleep(min(poll_interval_s, remaining_s))

    @QtCore.Slot(str)
    def interrupt_task(self, name: str) -> None:
        """Request interruption of a running task."""
        with self._thread_lock:
            task = self._running_tasks.get(name)

            if task is None:
                self.log.error(f'No ModuleTask with name "{name}" is running.')
                return
            self.log.info( f'Interrupt requested for ModuleTask "{name}".')
            task.interrupt()
            self.log.info(f"Task interruption flag: {task.interrupted}")


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