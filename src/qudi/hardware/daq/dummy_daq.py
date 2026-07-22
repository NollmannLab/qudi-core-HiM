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
sequences, or pump control should live in logic modules.

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
    _ao_voltage_range = ConfigOption("ao_voltage_range", default=(0, 10))
    _ao_channels = ConfigOption("ao_channels", default={})
    _ai_channels = ConfigOption("ai_channels", default={})
    _do_channels = ConfigOption("do_channels", default={})
    _di_channels = ConfigOption("di_channels", default={})

    def on_activate(self):
        """Populate the dummy task registry from the configured channels."""
        self._tasks = {}
        self._channel_data = {}
        self._channel_metadata = {}
        self._ao_voltage_ranges = {}

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
        self._tasks.clear()
        self._channel_data.clear()
        self._channel_metadata.clear()
        self._ao_voltage_ranges.clear()
        self.log.info("Dummy DAQ deactivated.")

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
            self._tasks[task_name] = taskhandle
            self._channel_metadata[taskhandle] = {
                "task_name": task_name,
                "channel": channel,
                "type": channel_type,
            }

            if channel_type in {"ao", "ai"}:
                self._channel_metadata[taskhandle]["voltage_range"] = tuple(voltage_range)
            if channel_type == "ao":
                self._ao_voltage_ranges[taskhandle] = tuple(voltage_range)
            self._channel_data[taskhandle] = default_value

    def get_taskhandle(self, task_name):
        """Return the dummy task handle for ``task_name``."""
        if task_name not in self._tasks:
            raise KeyError(f"Unknown DAQ task '{task_name}'.")
        return self._tasks[task_name]

    @staticmethod
    def create_taskhandle():
        """Create a new dummy task handle."""
        return object()

    def set_up_ao_channel(self, taskhandle, channel, voltage_range):
        """Store metadata for a dummy analog-output channel."""
        self._channel_metadata[taskhandle] = {
            "channel": channel,
            "type": "ao",
            "voltage_range": tuple(voltage_range),
        }
        self._channel_data[taskhandle] = 0.0

    def write_to_ao_channel(self, taskhandle, voltage, voltage_range=None, timeout=None, autostart=True):
        """Cache the analog-output voltage in memory."""
        if voltage_range is None:
            metadata = self._channel_metadata.get(taskhandle, {})
            voltage_range = metadata.get("voltage_range")
        if voltage_range is not None:
            min_voltage, max_voltage = voltage_range
            if not (min_voltage <= float(voltage) <= max_voltage):
                raise ValueError(
                    f"AO voltage {voltage} V is outside the allowed range "
                    f"[{min_voltage}, {max_voltage}] V."
                )
        _ = timeout if timeout is not None else self._rw_timeout
        _ = autostart
        self._channel_data[taskhandle] = float(voltage)

    def set_up_ai_channel(self, taskhandle, channel, voltage_range):
        """Store metadata for a dummy analog-input channel."""
        self._channel_metadata[taskhandle] = {
            "channel": channel,
            "type": "ai",
            "voltage_range": tuple(voltage_range),
        }
        self._channel_data[taskhandle] = 0.0

    def read_ai_channel(self, taskhandle):
        """Return the cached analog-input value.

        The dummy returns the last cached value if one has been written. This
        keeps the behavior predictable for logic and GUI testing.
        """
        return float(self._channel_data.get(taskhandle, 0.0))

    def set_up_do_channel(self, taskhandle, channel):
        """Store metadata for a dummy digital-output channel."""
        self._channel_metadata[taskhandle] = {
            "channel": channel,
            "type": "do",
        }
        self._channel_data[taskhandle] = np.uint8(0)

    def write_to_do_channel(self, taskhandle, num_samp, digital_write):
        """Cache the last digital output state."""
        _ = num_samp
        value = np.asarray(digital_write, dtype=np.uint8)
        self._channel_data[taskhandle] = value.copy()
        return value.size

    def set_up_di_channel(self, taskhandle, channel):
        """Store metadata for a dummy digital-input channel."""
        self._channel_metadata[taskhandle] = {
            "channel": channel,
            "type": "di",
        }
        self._channel_data[taskhandle] = np.zeros((1,), dtype=np.uint8)

    def read_di_channel(self, taskhandle, num_samp):
        """Return the cached digital input state."""
        value = self._channel_data.get(taskhandle, np.zeros((num_samp,), dtype=np.uint8))
        return np.asarray(value, dtype=np.uint8)

    def close_task(self, taskhandle):
        """Remove a task and its cached value from the dummy registry."""
        self._channel_data.pop(taskhandle, None)
        self._channel_metadata.pop(taskhandle, None)
        for task_name, handle in list(self._tasks.items()):
            if handle is taskhandle:
                self._tasks.pop(task_name, None)
                break

    def write_named_ao(self, task_name, voltage):
        """Write a value to a named dummy analog-output task."""
        taskhandle = self.get_taskhandle(task_name)
        return self.write_to_ao_channel(
            taskhandle,
            voltage,
            self._ao_voltage_ranges.get(taskhandle, self._ao_voltage_range),
        )

    def read_named_ai(self, task_name):
        """Read a value from a named dummy analog-input task."""
        taskhandle = self.get_taskhandle(task_name)
        value = float(self.read_ai_channel(taskhandle))
        self._channel_data[taskhandle] = value
        return value

    def write_named_do(self, task_name, value):
        """Write a value to a named dummy digital-output task."""
        digital_value = np.array([np.uint8(value)], dtype=np.uint8)
        taskhandle = self.get_taskhandle(task_name)
        self._channel_data[taskhandle] = np.uint8(value)
        return self.write_to_do_channel(taskhandle, 1, digital_value)

    def read_named_di(self, task_name, num_samp=1):
        """Read a value from a named dummy digital-input task."""
        taskhandle = self.get_taskhandle(task_name)
        value = self.read_di_channel(taskhandle, num_samp)
        self._channel_data[taskhandle] = value
        return value

    def pulse_named_do(self, task_name, low=0, high=1, pulse_time=0.001):
        """Simulate a low-high-low pulse on a named digital-output task."""
        self.write_named_do(task_name, low)
        sleep(pulse_time)
        self.write_named_do(task_name, high)
        sleep(pulse_time)
        self.write_named_do(task_name, low)
