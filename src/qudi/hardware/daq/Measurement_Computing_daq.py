# -*- coding: utf-8 -*-
"""
Author: F Barho - adapted for qudi-core-HiM by JB Fiche
Created: 2021-06-06 -> refactored for qudi-core on 2026-07-28

Hardware script to interface Measurement Computing DAQ (Acquisys).

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
import numpy as np

from uldaq import (get_daq_device_inventory, DaqDevice, InterfaceType, DaqDeviceInfo, AOutFlag,
                   AiInputMode, Range, AInFlag)
from qudi.core.configoption import ConfigOption
from qudi.interface.daq_interface import DaqInterface


# Define the A0 range
AO_RANGES = {
    'BIP10VOLTS': {
        'uldaq_range': Range.BIP10VOLTS,
        'minimum': -10.0,
        'maximum': 10.0,
        'unit': 'V',
    },
    'UNI10VOLTS': {
        'uldaq_range': Range.UNI10VOLTS,
        'minimum': 0.0,
        'maximum': 10.0,
        'unit': 'V',
    },
    'MA0TO20': {
        'uldaq_range': Range.MA0TO20,
        'minimum': 0.0,
        'maximum': 20.0,
        'unit': 'mA',
    },
}

# Define the AI range
AI_RANGES = {}

class MccDAQ(DaqInterface):
    """In-memory DAQ used for development and testing.

    In configuration, indicate which channels are connected.

      daq:
        module.Class: 'daq.Measurement_Computing_daq.MccDAQ'
        options:
          read_write_timeout: 10
          ao_channels:
             fluidics:
               - '/Dev1/AO1'  # physical channel on the daq
               - [0, 5]  # voltage range defined by the spec of the connected device. Max range is [-10, 10] V.
             rinsing_pump:
               - '/Dev1/AO0'
               - [ 0, 5 ]
            # laser_405:
            #   - '/Dev1/AO0'
            #   - [0, 10]
          ai_channels:
          do_channels:
          di_channels:

    Each mapping associates a semantic task name to a physical channel string,
    or to a ``[channel, voltage_range]`` pair for analog channels.
    """

    # config options
    _rw_timeout = ConfigOption("read_write_timeout", default=10)
    _ao_channels = ConfigOption("ao_channels", default={})
    _ai_channels = ConfigOption("ai_channels", default={})
    _do_channels = ConfigOption("do_channels", default={})
    _di_channels = ConfigOption("di_channels", default={})

    # attributes
    _device = None
    _ao_device = None
    _ai_device = None
    _do_device = None
    _di_device = None
    _tasks = {}
    _channel_metadata = {}
    _ao_voltage_ranges = {}
    _channel_data = {}


    def on_activate(self):
        """ Initialization steps when module is called.
        """
        try:
            # Get a list of available DAQ devices
            devices = get_daq_device_inventory(InterfaceType.USB)
            number_of_devices = len(devices)
            if number_of_devices == 0:
                raise RuntimeError('Error: No DAQ devices found')

            # Create a DaqDevice Object and connect to the device
            self._device = DaqDevice(devices[0])
            descriptor = self._device.get_descriptor()
            self.log.info(f'Connecting to {descriptor.dev_string} - please wait...')
            self._device.connect()

            # for each type of channel, register the tasks. In the case of MCC DAQ, a handle is defined by type, not by
            # channel. For example, all AO channels will share the same taskhandle.
            if self._ao_channels:
                self._ao_device = self.create_taskhandle("ao")
                self._register_channels(self._ao_channels, channel_type="ao", default_value=0.0)

            if self._ai_channels:
                self._ai_device = self.create_taskhandle("ai")
                self._register_channels(self._ai_channels, channel_type="ai", default_value=0.0)

            if self._do_channels:
                self._do_device = self.create_taskhandle("do")
                self._register_channels(self._do_channels, channel_type="do", default_value=np.uint8(0))

            if self._di_channels:
                self._di_device = self.create_taskhandle("di")
                self._register_channels(self._di_channels, channel_type="di", default_value=np.uint8(0))

        except Exception as e:
            self.log.error(f'Error during daq initialization: {e}')
            self.on_deactivate()
            raise

    def on_deactivate(self):
        """ Required deactivation steps.
        """
        if self._device:
            # Disconnect from the DAQ device.
            if self._device.is_connected():
                self._device.disconnect()
            # Release the DAQ device resource.
            self._device.release()

# ----------------------------------------------------------------------------------------------------------------------
# DAQ utility functions
# ----------------------------------------------------------------------------------------------------------------------

    def _register_channels(self, channel_map, channel_type, default_value):
        """Register configured channels in the task registry.

        Args:
            channel_map (dict): Mapping of task name to physical channel string.
            channel_type (str): One of ``ao``, ``ai``, ``do`` or ``di``.
            default_value: Initial value cached for the task.
        """
        for task_name, spec in dict(channel_map).items():
            if channel_type == "ao":
                channel, voltage_range = spec
                taskhandle = self._ao_device
            elif channel_type == "ai":
                channel, voltage_range, input_mode = spec
                taskhandle = self._ai_device
            elif channel_type == "di":
                channel = spec
                taskhandle = self._di_device
            else:
                channel = spec
                taskhandle = self._do_device

            self._tasks[task_name] = {
                "task_handle": taskhandle,
                "channel": channel,
                "type": channel_type,
            }

            if channel_type in {"ao", "ai"}:
                self._tasks[task_name]["voltage_range"] = voltage_range
            if channel_type == "ai":
                self._tasks[task_name]["input_mode"] = input_mode
            self._channel_data[taskhandle] = default_value

    def get_taskhandle(self, task_name):
        """Return the task handle associated with ``task_name``."""
        if task_name not in self._tasks:
            raise KeyError(f"Unknown DAQ task '{task_name}'.")
        return self._tasks[task_name]["task_handle"]

    def create_taskhandle(self, channel_type):
        """Create a new dummy task handle.
        Args: channel_type (str) indicate the type of channel handles
        """
        if channel_type == "ao":
            ao_device = self._device.get_ao_device()
            if ao_device is None:
                raise RuntimeError('Error: The DAQ device does not support analog output')
            else:
                return ao_device

        elif channel_type == "ai":
            ai_device = self._device.get_ai_device()
            if ai_device is None:
                raise RuntimeError('Error: The DAQ device does not support analog input')
            else:
                return ai_device

        else:
            raise RuntimeError('Error: Channel type is unkown or not yet configured')

    def write_to_ao_channel(self, voltage, taskhandle, channel, voltage_range):
        """Cache the analog-output voltage in memory."""
        min_voltage = AO_RANGES[voltage_range]['minimum']
        max_voltage = AO_RANGES[voltage_range]['maximum']
        unit = AO_RANGES[voltage_range]['unit']
        if not (min_voltage <= float(voltage) <= max_voltage):
            raise ValueError(
                f"AO voltage {voltage} V is outside the allowed range "
                f"[{min_voltage}, {max_voltage}] {unit}."
            )
        if taskhandle is not None:
            taskhandle.a_out(channel, AO_RANGES[voltage_range]['uldaq_range'], AOutFlag.DEFAULT, float(voltage))
        else:
            raise RuntimeError('Error: No task handle specified.')

    def write_named_ao(self, task_name, voltage):
        """Write a value to a named dummy analog-output task."""
        taskhandle = self._tasks[task_name]['task_handle']
        channel = self._tasks[task_name]['channel']
        voltage_range = self._tasks[task_name]['voltage_range']
        self.write_to_ao_channel(
            voltage,
            taskhandle,
            channel,
            voltage_range
        )

    def read_ai_channel(self, taskhandle, channel, input_mode, voltage_range):
        """Return the cached analog-input value.

        The dummy returns the last cached value if one has been written. This
        keeps the behavior predictable for logic and GUI testing.
        """
        if taskhandle is not None:
            data = taskhandle.a_in(channel, input_mode, AI_RANGES[voltage_range]['uldaq_range'], AInFlag.DEFAULT)
            return data
        else:
            raise RuntimeError('Error: No task handle specified.')

    def read_named_ai(self, task_name):
        """Read a value from a named dummy analog-input task."""
        taskhandle = self._tasks[task_name]['task_handle']
        channel = self._tasks[task_name]['channel']
        voltage_range = self._tasks[task_name]['voltage_range']
        input_mode = self._tasks[task_name]['input_mode']
        value = float(self.read_ai_channel(taskhandle, channel, input_mode, voltage_range))
        return value

