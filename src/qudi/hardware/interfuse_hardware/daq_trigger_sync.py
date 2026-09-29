# -*- coding: utf-8 -*-
"""
Author: JB Fiche with Claude code

Qudi-core-HiM interfuse hardware module: a single start/done trigger handshake with external
acquisition software (e.g. ZEN), implemented over a generic DAQ digital-output / digital-input
channel pair.

This follows the same pattern already used for the DAQ-driven pumps (see daq_pump_controller.py):
one interfuse instance wraps one physical channel pair behind a semantic interface, so tasks and
logic never talk to raw DAQ channel names directly.

-----------------------------------------------------------------------------------
qudi-core is free software: you can redistribute it and/or modify it under the terms of the GNU General Public License
as published by the Free Software Foundation, either version 3 of the License, or (at your option) any later version.

Qudi is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU General Public License for more details.

You should have received a copy of the GNU General Public License along with Qudi. If not, see <http://www.gnu.org/licenses/>.
-----------------------------------------------------------------------------------

Modified for qudi-core-HiM (2026-09-26, Modified with Claude code): new file - DAQ-backed
  implementation of TriggerSyncInterface, added to support a ZEN-synchronized stage-scan task on the
  spinning-disk setup. Written directly for qudi-core-HiM; no legacy equivalent existed as a
  standalone module (the legacy task talked to the DAQ hardware directly).

Modified for qudi-core-HiM (2026-09-28, Modified with Claude code): made trigger_channel optional,
  so one instance can be configured with only a done_channel and used purely to watch for a one-way
  signal ZEN raises on its own - send_trigger() then raises a clear error if ever called. This
  supports a second, distinct channel pair for the one-time "ZEN is ready" signal (matching the
  legacy task's OUT7_ZEN, a channel qudi only ever polled and never triggered), separate from the
  per-ROI start/done pair (matching OUT8_ZEN) - see tasks/roi_multicolour_scan_sd_task.py.
"""

from typing import Optional

from qudi.core.connector import Connector
from qudi.core.configoption import ConfigOption
from qudi.interface.daq_interface import DaqInterface
from qudi.interface.trigger_sync_interface import TriggerInputInterface, TriggerOutputInterface


class DaqTriggerOutput(TriggerOutputInterface):
    """Emit a finite trigger pulse through one configured named DAQ DO task.

    The ``output_trigger_task`` option is the semantic task name configured under the DAQ's
    ``do_channels`` mapping, not a physical channel number. ``pulse_time`` controls the high
    duration; the DAQ pulse operation returns the output low before this method returns.
    """

    daq = Connector(name='daq', interface='DaqInterface')

    _output_trigger_task = ConfigOption('output_trigger_task', missing='error')
    _pulse_time = ConfigOption('pulse_time', default=0.1, converter=float)
    _daq: Optional[DaqInterface] = None

    def on_activate(self) -> None:
        """Connect to the configured DAQ module."""
        self._daq = self.daq()

    def on_deactivate(self) -> None:
        """Release the DAQ module reference."""
        self._daq = None

    def send_trigger(self) -> None:
        """Emit one configured-width pulse, ending low before returning."""
        self._daq.pulse_named_do(
            self._output_trigger_task, low=0, high=1, pulse_time=self._pulse_time
        )


class DaqTriggerInput(TriggerInputInterface):
    """Sample one configured named DAQ DI task without blocking.

    The ``input_trigger_task`` option is the semantic task name configured under the DAQ's
    ``di_channels`` mapping, not a physical channel number. Waiting for a rising edge, timeout,
    or task interruption belongs to the caller's polling loop.
    """

    daq = Connector(name='daq', interface='DaqInterface')

    _input_trigger_task = ConfigOption('input_trigger_task', missing='error')

    _daq: Optional[DaqInterface] = None

    def on_activate(self) -> None:
        """Connect to the configured DAQ module."""
        self._daq = self.daq()

    def on_deactivate(self) -> None:
        """Release the DAQ module reference."""
        self._daq = None

    def is_triggered(self) -> bool:
        """Return the current sampled input state, without waiting for a trigger."""
        value = self._daq.read_named_di(self._input_trigger_task, num_samp=1)
        if hasattr(value, '__len__'):
            value = value[0]
        return bool(int(value))
