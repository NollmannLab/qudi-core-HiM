# -*- coding: utf-8 -*-
"""
Author: JB Fiche with codex - adapted for qudi-core-HiM from the previous daq script used in qudi-HiM
Created: 2026-07-21

Interface for the rinsing pump modules used by qudi-core-HiM.

This interface exposes the minimal contract required by the fluidics
logic and interfuse_hardware layers.

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


class PumpInterface(Base):
    """Interface for a controllable fluidics pump."""

    @abstractmethod
    def rinsing(self, voltage):
        """Set the pump-control voltage."""
        raise NotImplementedError

    @abstractmethod
    def stop(self):
        """Stop the pump."""
        raise NotImplementedError