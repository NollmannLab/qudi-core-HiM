# -*- coding: utf-8 -*-
"""
Author: JB Fiche with codex - adapted for qudi-core-HiM from the previous daq script used in qudi-HiM
Created: 2026-07-21

Interface for the pump hardware modules used by qudi-core-HiM.

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
from typing import Any, Dict, Optional, Sequence

from qudi.core.module import Base


class PumpInterface(Base):
    """Interface for pump hardware modules used by qudi-core-HiM."""

    @abstractmethod
    def set_output(self, param_dict: Dict[int, float]) -> None:
        """Set pump output values for one or more channels.

        Args:
            param_dict: Mapping of ``{channel_id: output_value}``. Concrete
                implementations may support one channel or multiple channels.
        """
        pass

    @abstractmethod
    def get_output(self, param_list: Optional[Sequence[int]] = None) -> Dict[int, float]:
        """Return output values for selected or all pump channels.

        Args:
            param_list: Optional sequence of channel IDs to query. If ``None``,
                the implementation should return all configured channels.

        Returns:
            A mapping of ``{channel_id: output_value}``.
        """
        pass

    @abstractmethod
    def get_constraints(self) -> Dict[str, Any]:
        """Return output limits and units for the pump."""
        pass

    @abstractmethod
    def stop(self) -> None:
        """Set the pump to its safe stopped state."""
        pass
