# -*- coding: utf-8 -*-
"""
Interface for a simple hardware start/done trigger handshake with external acquisition software
(e.g. ZEN) used by qudi-core-HiM tasks.

The interface is intentionally minimal: it exposes a single request/acknowledge pair (send a start
pulse, poll whether the "done" signal has been seen) and nothing else. Any polling loop, timeout, or
cooperative-interrupt handling belongs in the calling ModuleTask (see qudi.tasks), not here - this
keeps the interfuse hardware-agnostic and free of any dependency on qudi-core's task/interrupt
machinery.

-----------------------------------------------------------------------------------
qudi-core is free software: you can redistribute it and/or modify it under the terms of the GNU General Public License
as published by the Free Software Foundation, either version 3 of the License, or (at your option) any later version.

Qudi is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU General Public License for more details.

You should have received a copy of the GNU General Public License along with Qudi. If not, see <http://www.gnu.org/licenses/>.
-----------------------------------------------------------------------------------

Modified for qudi-core-HiM (2026-09-26, Modified with Claude code): new file - interface for the
  DaqTriggerSync interfuse (see hardware/interfuse_hardware/daq_trigger_sync.py), added to support a
  ZEN-synchronized stage-scan task on the spinning-disk setup.
"""

from abc import abstractmethod

from qudi.core.module import Base


class TriggerOutputInterface(Base):
    """Interface for hardware that emits a configured trigger pulse."""

    @abstractmethod
    def send_trigger(self) -> None:
        """Emit a single trigger pulse and return after the pulse has ended."""
        pass


class TriggerInputInterface(Base):
    """Interface for hardware that samples a configured trigger input."""

    @abstractmethod
    def is_triggered(self) -> bool:
        """Return the current trigger input state without waiting for an edge."""
        pass
