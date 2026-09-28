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
from qudi.interface.trigger_sync_interface import TriggerSyncInterface


class DaqTriggerSync(TriggerSyncInterface):
    """Send a start trigger to, and detect a done trigger from, external acquisition software
    through a generic DAQ.

    One instance handles a single named trigger-out / trigger-in channel pair. Config example:

    .. code-block:: yaml

        zen_acquisition_sync:
          module.Class: 'interfuse_hardware.daq_trigger_sync.DaqTriggerSync'
          connect:
            daq: 'daq'
          options:
            trigger_channel: 'zen_start'   # name of a do_channel configured on the connected daq
            done_channel: 'zen_done'       # name of a di_channel configured on the connected daq
            pulse_time: 0.1                 # seconds, passed to daq.pulse_named_do

    ``trigger_channel`` and ``done_channel`` must match named ``do_channels`` / ``di_channels``
    entries configured on the connected daq hardware module.

    ``trigger_channel`` may be omitted for an instance that only ever needs to watch for a one-way
    signal the external program raises on its own (e.g. a "ready" line) - ``send_trigger()`` then
    raises ``RuntimeError`` if it is ever called on that instance:

    .. code-block:: yaml

        zen_ready_sync:
          module.Class: 'interfuse_hardware.daq_trigger_sync.DaqTriggerSync'
          connect:
            daq: 'daq'
          options:
            done_channel: 'zen_ready'      # name of a di_channel configured on the connected daq
    """

    daq = Connector(name='daq', interface='DaqInterface')

    _trigger_channel = ConfigOption('trigger_channel', default=None)
    _done_channel = ConfigOption('done_channel', missing='error')
    _pulse_time = ConfigOption('pulse_time', default=0.1, converter=float)

    _daq: Optional[DaqInterface] = None

    def on_activate(self) -> None:
        """Connect to the DAQ backend."""
        self._daq = self.daq()

    def on_deactivate(self) -> None:
        """Release the DAQ backend."""
        self._daq = None

    def send_trigger(self) -> None:
        """Emit a single start-trigger pulse on the configured output channel.

        Raises:
            RuntimeError: if this instance was configured without a trigger_channel (a watch-only
                instance for a one-way signal - see class docstring).
        """
        if self._trigger_channel is None:
            raise RuntimeError(
                'This DaqTriggerSync instance has no trigger_channel configured - it can only be '
                'used to poll is_triggered(), not to send a trigger.')
        self._daq.pulse_named_do(self._trigger_channel, low=0, high=1, pulse_time=self._pulse_time)

    def is_triggered(self) -> bool:
        """Return True if the configured input channel currently reports the "done" signal."""
        value = self._daq.read_named_di(self._done_channel, num_samp=1)
        if hasattr(value, '__len__'):
            value = value[0]
        return bool(int(value))
