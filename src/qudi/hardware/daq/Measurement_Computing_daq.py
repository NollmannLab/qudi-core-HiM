# -*- coding: utf-8 -*-
"""Low-level Measurement Computing DAQ driver using MCC's UL for Linux (uldaq).

Named channel mappings use analog channel numbers for AO (and AI where a device
supports it), and DIO bit numbers for DO/DI. The USB-3104 exposes eight
individually configurable DIO bits, numbered 0 through 7.

Experiment-specific behavior belongs in interfuse modules, not in this driver.

Author: F Barho - adapted for qudi-core-HiM by JB Fiche
Created: 2021-06-06 -> refactored for qudi-core on 2026-07-28
Latest modifications -> add digital channel handling

-----------------------------------------------------------------------------------
qudi-core is free software: you can redistribute it and/or modify it under the terms of the GNU
General Public License as published by the Free Software Foundation, either version 3 of the
License, or (at your option) any later version.

Qudi is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY; without even the
implied warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU General Public
License for more details.
-----------------------------------------------------------------------------------
"""

from time import sleep

import numpy as np
from uldaq import (
    get_daq_device_inventory,
    DaqDevice,
    InterfaceType,
    AOutFlag,
    AiInputMode,
    Range,
    AInFlag,
    DigitalDirection,
    DigitalPortIoType,
)

from qudi.core.configoption import ConfigOption
from qudi.interface.daq_interface import DaqInterface


AO_RANGES = {
    "BIP10VOLTS": {
        "uldaq_range": Range.BIP10VOLTS,
        "minimum": -10.0,
        "maximum": 10.0,
        "unit": "V",
    },
    "UNI10VOLTS": {
        "uldaq_range": Range.UNI10VOLTS,
        "minimum": 0.0,
        "maximum": 10.0,
        "unit": "V",
    },
    "MA0TO20": {
        "uldaq_range": Range.MA0TO20,
        "minimum": 0.0,
        "maximum": 20.0,
        "unit": "mA",
    },
}


class MccDAQ(DaqInterface):
    """MCC DAQ driver with named AO, AI, DO and DI channels.

    Example configuration::

          daq:
            module.Class: 'daq.Measurement_Computing_daq.MccDAQ'
            options:
              read_write_timeout: 10
              ao_channels:
                 fluidics_pump:
                   - 0  # physical channel on the daq
                   - UNI10VOLTS # voltage range defined by the spec of the connected device. Here [-10, 10] V.
                 rinsing_pump:
                   - 1
                   - UNI10VOLTS
              ai_channels:
                   - 0  # physical channel on the daq
                   - UNI10VOLTS # voltage range defined by the spec of the connected device. Here [-10, 10] V.
                   - SINGLE_ENDED  # DIFFERENTIAL
              do_channels:
                start_block: 1
              di_channels:
                zen_ready: 0
                block_finished: 3

    DIO values are zero-based bit numbers. DO and DI channels may share the
    same eight-bit port, but a physical bit must be configured in only one
    direction at a time. The USB-3104 has no analog input subsystem; configuring
    ``ai_channels`` on that model raises a clear activation error.
    """

    _rw_timeout = ConfigOption("read_write_timeout", default=10, converter=float)
    _ao_channels = ConfigOption("ao_channels", default={})
    _ai_channels = ConfigOption("ai_channels", default={})
    _do_channels = ConfigOption("do_channels", default={})
    _di_channels = ConfigOption("di_channels", default={})

    def on_activate(self):
        """Connect to the first detected USB MCC DAQ and register configured channels.

        Analog channel mappings use ``[channel, range]`` for AO and
        ``[channel, range, input_mode]`` for AI. Digital mappings use an integer
        DIO bit index. The configured channel sets are validated and the
        requested DIO bit directions are applied during activation.

        Raises:
            RuntimeError: If no device is found or a configured I/O subsystem
                is not supported by the connected device.
            ValueError: If a channel specification or DIO assignment is invalid.
        """
        self._reset_registry()
        self._device = None
        self._ao_device = None
        self._ai_device = None
        self._dio_device = None
        self._dio_port = None

        try:
            devices = get_daq_device_inventory(InterfaceType.USB)
            if not devices:
                raise RuntimeError("No MCC DAQ devices found.")

            self._device = DaqDevice(devices[0])
            descriptor = self._device.get_descriptor()
            self.log.info(f"Connecting to {descriptor.dev_string} - please wait...")
            self._device.connect()

            if self._ao_channels:
                self._ao_device = self._device.get_ao_device()
                if self._ao_device is None:
                    raise RuntimeError("The connected DAQ does not support analog output.")
                self._register_analog_channels(self._ao_channels, "ao")

            if self._ai_channels:
                self._ai_device = self._device.get_ai_device()
                if self._ai_device is None:
                    raise RuntimeError("The connected DAQ does not support analog input.")
                self._register_analog_channels(self._ai_channels, "ai")

            if self._do_channels or self._di_channels:
                self._configure_digital_channels()

            self.log.info("MCC DAQ activated.")
        except Exception:
            self.on_deactivate()
            raise

    def on_deactivate(self):
        """Disconnect and release the MCC device, then clear registered channels."""
        device = getattr(self, "_device", None)
        if device is not None:
            try:
                if device.is_connected():
                    device.disconnect()
            finally:
                device.release()
        self._device = None
        self._ao_device = None
        self._ai_device = None
        self._dio_device = None
        self._dio_port = None
        self._reset_registry()

    def _reset_registry(self):
        """Clear task handles and cached values for all configured channels."""
        self._tasks = {}
        self._channel_data = {}

    @staticmethod
    def _channel_number(channel, channel_type):
        """Validate and return a non-negative, zero-based channel number.

        Args:
            channel: Configured channel index.
            channel_type: Channel family name used in validation errors.

        Returns:
            int: Normalized channel index.

        Raises:
            ValueError: If ``channel`` is not an integer-like value or is negative.
        """
        try:
            number = int(channel)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"{channel_type.upper()} channel must be a scalar numeric, zero-based channel "
                f"index (not a list); "
                f"got {channel!r}."
            ) from exc
        if number < 0:
            raise ValueError(f"{channel_type.upper()} channel index cannot be negative: {number}.")
        return number

    def _register_analog_channels(self, channel_map, channel_type):
        """Validate and register named analog channels in the internal registry.

        AO entries use ``[channel, range_name]`` with a range in ``AO_RANGES``.
        AI entries use ``[channel, range, input_mode]``. String AI range and mode
        names are resolved to the corresponding `uldaq` enum values.

        Args:
            channel_map (Mapping[str, Sequence]): Named analog channel settings.
            channel_type (str): Either ``"ao"`` or ``"ai"``.

        Raises:
            ValueError: If a channel setting is malformed or uses an unknown range/mode.
        """
        for task_name, spec in dict(channel_map).items():
            if channel_type == "ao":
                if len(spec) != 2:
                    raise ValueError(f"AO task {task_name!r} must be [channel, range].")
                channel, voltage_range = spec
                if voltage_range not in AO_RANGES:
                    raise ValueError(
                        f"Unsupported AO range {voltage_range!r} for task {task_name!r}; "
                        f"choose one of {tuple(AO_RANGES)}."
                    )
                input_mode = None
                taskhandle = self._ao_device
            else:
                if len(spec) != 3:
                    raise ValueError(f"AI task {task_name!r} must be [channel, range, input_mode].")
                channel, voltage_range, input_mode = spec
                if isinstance(voltage_range, str):
                    try:
                        voltage_range = getattr(Range, voltage_range)
                    except AttributeError as exc:
                        raise ValueError(
                            f"Unknown MCC analog-input range {voltage_range!r} "
                            f"for task {task_name!r}."
                        ) from exc
                if isinstance(input_mode, str):
                    try:
                        input_mode = getattr(AiInputMode, input_mode)
                    except AttributeError as exc:
                        raise ValueError(
                            f"Unknown MCC analog-input mode {input_mode!r} "
                            f"for task {task_name!r}."
                        ) from exc
                taskhandle = self._ai_device

            self._tasks[task_name] = {
                "task_handle": object(),
                "task_name": task_name,
                "backend": taskhandle,
                "channel": self._channel_number(channel, channel_type),
                "type": channel_type,
                "voltage_range": voltage_range,
                "input_mode": input_mode,
            }
            self._channel_data[task_name] = 0.0

    def _configure_digital_channels(self):
        """Discover a bit-configurable DIO port and register configured DO/DI bits.

        Each physical bit can be assigned to only one named task and one
        direction. Each output is explicitly driven low immediately after its
        direction is enabled. The USB-3104's `uldaq` interface does not expose
        a supported initial-output-latch preload operation.

        Raises:
            RuntimeError: If the device has no usable DIO subsystem or port.
            ValueError: If a bit index is invalid or assigned more than once.
        """
        self._dio_device = self._device.get_dio_device()
        if self._dio_device is None:
            raise RuntimeError("The connected DAQ does not support digital I/O.")

        dio_info = self._dio_device.get_info()
        port_types = dio_info.get_port_types()
        if not port_types:
            raise RuntimeError("The connected DAQ reports no digital I/O ports.")

        # The USB-3104 reports its 8-bit port as AUXPORT. Select a bitwise
        # configurable port, and reject devices whose DIO cannot mix directions.
        candidates = []
        for port_type in port_types:
            port_info = dio_info.get_port_info(port_type)
            if port_info.port_io_type == DigitalPortIoType.BITIO:
                candidates.append((port_type, port_info.number_of_bits))
        if not candidates:
            raise RuntimeError("The connected DAQ has no bitwise-configurable DIO port.")
        self._dio_port, bit_count = candidates[0]

        requested = {}
        # The USB-3104 does not support uldaq's set_port_initial_output_val
        # configuration operation. Configure each requested bit individually,
        # then immediately drive every output low using the supported bit I/O.
        for channel_type, channel_map in (("do", self._do_channels), ("di", self._di_channels)):
            for task_name, channel in dict(channel_map).items():
                bit = self._channel_number(channel, channel_type)
                if bit >= bit_count:
                    raise ValueError(
                        f"DIO bit {bit} for task {task_name!r} is outside the available range "
                        f"0..{bit_count - 1}."
                    )
                if bit in requested:
                    raise ValueError(
                        f"DIO bit {bit} is assigned to both {requested[bit]!r} and {task_name!r}; "
                        "each bit must have one task and one direction."
                    )
                requested[bit] = task_name

                direction = (DigitalDirection.OUTPUT if channel_type == "do"
                             else DigitalDirection.INPUT)
                self._dio_device.d_config_bit(self._dio_port, bit, direction)
                taskhandle = object()
                self._tasks[task_name] = {
                    "task_handle": taskhandle,
                    "task_name": task_name,
                    "backend": self._dio_device,
                    "channel": bit,
                    "port": self._dio_port,
                    "type": channel_type,
                }
                self._channel_data[task_name] = np.uint8(0)

                if channel_type == "do":
                    # Establish a known idle-low state without changing other bits.
                    self._dio_device.d_bit_out(self._dio_port, bit, 0)

    def _get_task(self, task_name):
        """Return registered task metadata or raise for an unknown task name."""
        try:
            return self._tasks[task_name]
        except KeyError as exc:
            raise KeyError(f"Unknown DAQ task {task_name!r}.") from exc

    def _get_task_from_handle(self, taskhandle):
        """Find a registered task by its opaque interface handle.

        Raises:
            RuntimeError: If the handle does not belong to a configured channel.
        """
        for task in self._tasks.values():
            if task["task_handle"] is taskhandle:
                return task
        raise RuntimeError("Unknown DAQ task handle.")

    @staticmethod
    def create_taskhandle():
        """Create an opaque token for a configured named channel."""
        return object()

    def get_taskhandle(self, task_name):
        """Return the opaque low-level handle for a named configured channel.

        Args:
            task_name (str): Name from one of the configured channel mappings.
        """
        return self._get_task(task_name)["task_handle"]

    def get_task_range(self, task_name):
        """Return analog-output bounds as ``(minimum, maximum)`` or ``None``.

        The returned bounds are used by higher-level controllers, including
        the laser controller, to scale output values. Non-AO channels have no
        voltage range and return ``None``.
        """
        task = self._get_task(task_name)
        if task["type"] != "ao":
            return None
        range_info = AO_RANGES[task["voltage_range"]]
        return (range_info["minimum"], range_info["maximum"])

    def write_to_ao_channel(self, taskhandle, voltage, voltage_range=None, timeout=None, autostart=True):
        """Write one voltage to a configured AO channel.

        Args:
            taskhandle: Opaque handle returned by :meth:`get_taskhandle`.
            voltage (float): Output value in the units of the configured range.
            voltage_range: Optional configured range name or ``(min, max)`` pair.
            timeout: Accepted for interface compatibility; `uldaq.a_out` is an
                immediate scalar operation and does not use this value.
            autostart (bool): Accepted for interface compatibility; output is
                written immediately by `uldaq.a_out`.

        Raises:
            TypeError: If the handle does not refer to an AO channel.
            ValueError: If the range does not match or the voltage is out of range.
        """
        task = self._get_task_from_handle(taskhandle)
        if task["type"] != "ao":
            raise TypeError("The supplied task handle is not an analog-output task.")
        range_name = task["voltage_range"]
        range_info = AO_RANGES[range_name]
        if voltage_range is not None and voltage_range != range_name:
            # Also accept the (min, max) range tuple used by the shared DAQ interface.
            if tuple(voltage_range) != (range_info["minimum"], range_info["maximum"]):
                raise ValueError(f"Voltage range {voltage_range!r} does not match {range_name!r}.")
        voltage = float(voltage)
        if not range_info["minimum"] <= voltage <= range_info["maximum"]:
            raise ValueError(
                f"AO value {voltage} {range_info['unit']} is outside the allowed range "
                f"[{range_info['minimum']}, {range_info['maximum']}]."
            )
        _ = timeout if timeout is not None else self._rw_timeout
        _ = autostart
        self._ao_device.a_out(
            task["channel"], range_info["uldaq_range"], AOutFlag.DEFAULT, voltage
        )
        self._channel_data[self._task_name(task)] = voltage

    def read_ai_channel(self, taskhandle):
        """Read one scalar voltage from a configured analog-input channel.

        Args:
            taskhandle: Opaque handle returned by :meth:`get_taskhandle`.

        Returns:
            float: Measured input voltage.

        Raises:
            TypeError: If the handle does not refer to an AI channel.
        """
        task = self._get_task_from_handle(taskhandle)
        if task["type"] != "ai":
            raise TypeError("The supplied task handle is not an analog-input task.")
        data = self._ai_device.a_in(
            task["channel"], task["input_mode"], task["voltage_range"], AInFlag.DEFAULT
        )
        return float(data)

    def write_to_do_channel(self, taskhandle, num_samp, digital_write):
        """Write sequential 0/1 values to one configured digital-output bit.

        MCC's bit I/O call writes one value at a time, so this method applies
        each supplied sample in sequence and leaves the output at its last
        value.

        Args:
            taskhandle: Opaque handle returned by :meth:`get_taskhandle`.
            num_samp (int): Number of values in ``digital_write``.
            digital_write: Iterable of digital values, each either 0 or 1.

        Returns:
            int: Number of output values written.

        Raises:
            TypeError: If the handle does not refer to a DO channel.
            ValueError: If the sample count or values are invalid.
        """
        task = self._get_task_from_handle(taskhandle)
        if task["type"] != "do":
            raise TypeError("The supplied task handle is not a digital-output task.")
        raw_values = np.asarray(digital_write).reshape(-1)
        if np.any((raw_values != 0) & (raw_values != 1)):
            raise ValueError("Digital output values must be 0 or 1.")
        values = raw_values.astype(np.uint8)
        if len(values) != int(num_samp):
            raise ValueError("num_samp must match the number of supplied digital output values.")
        for value in values:
            self._dio_device.d_bit_out(task["port"], task["channel"], int(value))
        self._channel_data[self._task_name(task)] = np.uint8(values[-1]) if values.size else np.uint8(0)
        return int(values.size)

    def read_di_channel(self, taskhandle, num_samp):
        """Read ``num_samp`` immediate samples from one DI bit.

        The USB-3104 path reads the current bit value once per sample; it does
        not start a buffered input scan. Returned data is a uint8 NumPy array
        containing zeros and ones.

        Args:
            taskhandle: Opaque handle returned by :meth:`get_taskhandle`.
            num_samp (int): Positive number of immediate reads to perform.

        Returns:
            numpy.ndarray: Digital samples with dtype ``uint8``.

        Raises:
            TypeError: If the handle does not refer to a DI channel.
            ValueError: If ``num_samp`` is less than one.
        """
        task = self._get_task_from_handle(taskhandle)
        if task["type"] != "di":
            raise TypeError("The supplied task handle is not a digital-input task.")
        count = int(num_samp)
        if count < 1:
            raise ValueError("num_samp must be at least 1.")
        values = np.fromiter(
            (self._dio_device.d_bit_in(task["port"], task["channel"]) for _ in range(count)),
            dtype=np.uint8,
            count=count,
        )
        self._channel_data[self._task_name(task)] = values.copy()
        return values

    def _task_name(self, task):
        """Return the configured name stored in a task metadata record."""
        return task["task_name"]

    def write_named_ao(self, task_name, voltage):
        """Write a voltage to a named AO channel using its configured range.

        Args:
            task_name (str): Configured AO task name.
            voltage (float): Output voltage or current setpoint, according to
                the configured range.
        """
        task = self._get_task(task_name)
        return self.write_to_ao_channel(task["task_handle"], voltage)

    def read_named_ai(self, task_name):
        """Read and return the current scalar value from a named AI channel.

        Args:
            task_name (str): Configured AI task name.

        Returns:
            float: Measured input value.
        """
        task = self._get_task(task_name)
        value = self.read_ai_channel(task["task_handle"])
        self._channel_data[task_name] = value
        return value

    def write_named_do(self, task_name, value):
        """Set a named digital-output channel to logic low (0) or high (1).

        Args:
            task_name (str): Configured DO task name.
            value (int): Digital output state, either 0 or 1.

        Raises:
            ValueError: If ``value`` is not 0 or 1.
        """
        task = self._get_task(task_name)
        try:
            numeric_value = float(value)
        except (TypeError, ValueError) as exc:
            raise ValueError("Digital output values must be 0 or 1.") from exc
        if numeric_value not in (0.0, 1.0):
            raise ValueError("Digital output values must be 0 or 1.")
        value = int(numeric_value)
        return self.write_to_do_channel(task["task_handle"], 1, np.array([value], dtype=np.uint8))

    def read_named_di(self, task_name, num_samp=1):
        """Read immediate digital samples from a named DI channel.

        Args:
            task_name (str): Configured DI task name.
            num_samp (int): Number of immediate reads; defaults to one.

        Returns:
            numpy.ndarray: Digital samples with dtype ``uint8``.
        """
        task = self._get_task(task_name)
        return self.read_di_channel(task["task_handle"], num_samp)

    def pulse_named_do(self, task_name, low=0, high=1, pulse_time=0.001):
        """Emit a low-high-low pulse on a named digital-output channel.

        The output is first set to ``low``, held for ``pulse_time``, set to
        ``high`` for ``pulse_time``, then returned to ``low``. Thus
        ``pulse_time`` controls the high pulse width and also provides an
        initial low interval before the rising edge.

        Args:
            task_name (str): Configured DO task name.
            low (int): Low logic level, either 0 or 1.
            high (int): High logic level, either 0 or 1, and different from low.
            pulse_time (float): Duration in seconds for each level interval.

        Raises:
            ValueError: If levels are invalid or ``pulse_time`` is negative.
        """
        low, high = int(low), int(high)
        if low not in (0, 1) or high not in (0, 1) or low == high:
            raise ValueError("Pulse low and high levels must be distinct values from {0, 1}.")
        pulse_time = float(pulse_time)
        if pulse_time < 0:
            raise ValueError("pulse_time cannot be negative.")
        self.write_named_do(task_name, low)
        if pulse_time:
            sleep(pulse_time)
        self.write_named_do(task_name, high)
        if pulse_time:
            sleep(pulse_time)
        self.write_named_do(task_name, low)
