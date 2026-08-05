# -*- coding: utf-8 -*-
"""
Author: F Barho - adapted for qudi-core-HiM by JB Fiche
Created: 2026-07-21

Generic dummy to emulate National Instruments DAQ hardware driver.

This module intentionally contains only low-level DAQ operations:
- create and close tasks
- configure AI/AO/DI/DO channels
- read and write scalar values

Higher-level experiment behavior such as laser control, piezo motion, trigger
sequences, or pump control are defined as interfuse hardware instruments.

-----------------------------------------------------------------------------------
qudi-core is free software: you can redistribute it and/or modify it under the terms of the GNU General Public License
as published by the Free Software Foundation, either version 3 of the License, or (at your option) any later version.

Qudi is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU General Public License for more details.

You should have received a copy of the GNU General Public License along with Qudi. If not, see <http://www.gnu.org/licenses/>.
-----------------------------------------------------------------------------------
"""

from time import sleep
import numpy as np
from qudi.core.configoption import ConfigOption
from qudi.interface.daq_interface import DaqInterface


class DummyDaq(DaqInterface):
    """In-memory DAQ used for development and testing.

    The dummy uses the same named channel configuration as the real hardware
    driver:

    - ``ao_channels``
    - ``ai_channels``
    - ``do_channels``
    - ``di_channels``

    Each mapping associates a semantic task name to a physical channel string,
    or to a ``[channel, voltage_range]`` pair for analog channels. In the
    dummy implementation the physical channel string is stored for completeness
    but not used to communicate with hardware.
    """

    _rw_timeout = ConfigOption("read_write_timeout", default=10)
    _ao_channels = ConfigOption("ao_channels", default={})
    _ai_channels = ConfigOption("ai_channels", default={})
    _do_channels = ConfigOption("do_channels", default={})
    _di_channels = ConfigOption("di_channels", default={})

    def on_activate(self):
        """Populate the dummy task registry from the configured channels."""
        self._reset_task_registry()

        if self._ao_channels:
            self._register_channels(self._ao_channels, channel_type="ao", default_value=0.0)

        if self._ai_channels:
            self._register_channels(self._ai_channels, channel_type="ai", default_value=0.0)

        if self._do_channels:
            self._register_channels(self._do_channels, channel_type="do", default_value=np.uint8(0))

        if self._di_channels:
            self._register_channels(self._di_channels, channel_type="di", default_value=np.uint8(0))

        self.log.info("Dummy DAQ activated.")

    def on_deactivate(self):
        """Clear the in-memory task registry."""
        self._reset_task_registry()
        self.log.info("Dummy DAQ deactivated.")

    def _reset_task_registry(self):
        """Create a fresh in-memory registry for all configured tasks."""
        self._tasks = {}
        self._channel_data = {}

    def _register_channels(self, channel_map, channel_type, default_value):
        """Register configured channels in the dummy task registry.

        Args:
            channel_map (dict): Mapping of task name to physical channel string.
            channel_type (str): One of ``ao``, ``ai``, ``do`` or ``di``.
            default_value: Initial value cached for the task.
        """
        for task_name, spec in dict(channel_map).items():
            if channel_type in {"ao", "ai"}:
                channel, voltage_range = spec
            else:
                channel = spec

            taskhandle = self.create_taskhandle()
            self._tasks[task_name] = {
                "task_handle": taskhandle,
                "task_name": task_name,
                "channel": channel,
                "type": channel_type,
            }

            if channel_type in {"ao", "ai"}:
                self._tasks[task_name]["voltage_range"] = tuple(voltage_range)
            self._channel_data[task_name] = default_value

    def get_taskhandle(self, task_name):
        """Return the dummy task handle for ``task_name``."""
        if task_name not in self._tasks:
            raise KeyError(f"Unknown DAQ task '{task_name}'.")
        return self._tasks[task_name]["task_handle"]

    def get_task_range(self, task_name):
        """Return the task range for ``task_name``, if task is associated to an analog channel."""
        if task_name not in self._tasks:
            raise KeyError(f"Unknown DAQ task '{task_name}'.")

        task = self._tasks[task_name]
        if task["type"] == "ao":
            return task["voltage_range"]
        else:
            return None

    def _get_task(self, task_name):
        """Return the stored task metadata for ``task_name``."""
        if task_name not in self._tasks:
            raise KeyError(f"Unknown DAQ task '{task_name}'.")
        return self._tasks[task_name]

    def _get_task_name_from_handle(self, taskhandle):
        """Return the task name associated with ``taskhandle``."""
        for task_name, task in self._tasks.items():
            if task["task_handle"] is taskhandle:
                return task_name
        raise RuntimeError("Error: No task handle specified.")

    @staticmethod
    def create_taskhandle():
        """Create a new dummy task handle."""
        return object()

    def write_to_ao_channel(self, taskhandle, voltage, voltage_range=None, timeout=None, autostart=True):
        """Cache the analog-output voltage in memory."""
        task_name = self._get_task_name_from_handle(taskhandle)
        if voltage_range is None:
            voltage_range = self._tasks[task_name].get("voltage_range")
        if voltage_range is not None:
            min_voltage, max_voltage = voltage_range
            if not (min_voltage <= float(voltage) <= max_voltage):
                raise ValueError(
                    f"AO voltage {voltage} V is outside the allowed range "
                    f"[{min_voltage}, {max_voltage}] V."
                )
        _ = timeout if timeout is not None else self._rw_timeout
        _ = autostart
        self._channel_data[task_name] = float(voltage)

    def read_ai_channel(self, taskhandle):
        """Return the cached analog-input value.

        The dummy returns the last cached value if one has been written. This
        keeps the behavior predictable for logic and GUI testing.
        """
        task_name = self._get_task_name_from_handle(taskhandle)
        return float(self._channel_data.get(task_name, 0.0))

    def write_to_do_channel(self, taskhandle, num_samp, digital_write):
        """Cache the last digital output state."""
        _ = num_samp
        value = np.asarray(digital_write, dtype=np.uint8)
        task_name = self._get_task_name_from_handle(taskhandle)
        self._channel_data[task_name] = value.copy()
        return value.size

    def read_di_channel(self, taskhandle, num_samp):
        """Return the cached digital input state."""
        task_name = self._get_task_name_from_handle(taskhandle)
        value = self._channel_data.get(task_name, np.zeros((num_samp,), dtype=np.uint8))
        return np.asarray(value, dtype=np.uint8)

    def write_named_ao(self, task_name, voltage):
        """Write a value to a named dummy analog-output task."""
        task = self._get_task(task_name)
        return self.write_to_ao_channel(
            task["task_handle"],
            voltage,
            task.get("voltage_range"),
        )

    def read_named_ai(self, task_name):
        """Read a value from a named dummy analog-input task."""
        task = self._get_task(task_name)
        value = float(self.read_ai_channel(task["task_handle"]))
        self._channel_data[task_name] = value
        return value

    def write_named_do(self, task_name, value):
        """Write a value to a named dummy digital-output task."""
        digital_value = np.array([np.uint8(value)], dtype=np.uint8)
        task = self._get_task(task_name)
        self._channel_data[task_name] = np.uint8(value)
        return self.write_to_do_channel(task["task_handle"], 1, digital_value)

    def read_named_di(self, task_name, num_samp=1):
        """Read a value from a named dummy digital-input task."""
        task = self._get_task(task_name)
        value = self.read_di_channel(task["task_handle"], num_samp)
        self._channel_data[task_name] = value
        return value

    def pulse_named_do(self, task_name, low=0, high=1, pulse_time=0.001):
        """Simulate a low-high-low pulse on a named digital-output task."""
        self.write_named_do(task_name, low)
        sleep(pulse_time)
        self.write_named_do(task_name, high)
        sleep(pulse_time)
        self.write_named_do(task_name, low)
