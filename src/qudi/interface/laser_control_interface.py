# -*- coding: utf-8 -*-
"""
Author: JB Fiche with codex - adapted for qudi-core-HiM from the previous daq script used in qudi-HiM
Created: 2026-07-21

Interface for laser control modules used by qudi-core-HiM.

This interface exposes the minimal contract required by the laser-control
logic and interfuse_hardware layers:

- provide a metadata dictionary describing available laser channels
- apply a control value to one selected laser channel
- switch all laser channels off

-----------------------------------------------------------------------------------
qudi-core is free software: you can redistribute it and/or modify it under the terms of the GNU General Public License
as published by the Free Software Foundation, either version 3 of the License, or (at your option) any later version.

Qudi is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU General Public License for more details.

You should have received a copy of the GNU General Public License along with Qudi. If not, see <http://www.gnu.org/licenses/>.
-----------------------------------------------------------------------------------
"""

from abc import abstractmethod
from qudi.core.module import Base


class LasercontrolInterface(Base):
    """Interface for hardware or interfuse_hardware modules controlling lasers."""

    @abstractmethod
    def get_dict(self):
        """Return metadata for the available laser channels."""
        pass

    @abstractmethod
    def apply_voltage(self, voltage, channel):
        """Apply a control voltage/value to one laser channel."""
        pass

    @abstractmethod
    def disable_all(self):
        """Set all laser outputs to a safe inactive state."""
        pass
