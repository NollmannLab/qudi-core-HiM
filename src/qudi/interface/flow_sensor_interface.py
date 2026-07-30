# -*- coding: utf-8 -*-
"""
Author: JB Fiche with codex - adapted for qudi-core-HiM from the previous daq script used in qudi-HiM
Created: 2026-07-29

Interface for the flow sensor hardware modules used by qudi-core-HiM.

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
from typing import Dict, Optional, Sequence

from qudi.core.module import Base


class FlowSensorInterface(Base):
    """Interface for hardware exposing flow-sensor channels."""

    @abstractmethod
    def get_flowrate(self, param_list: Optional[Sequence[int]] = None) -> Dict[int, float]:
        """Return flowrate values for selected or all sensor channels.

        Args:
            param_list: Optional sequence of sensor channel IDs to query. If
                ``None``, the implementation should return all configured
                sensor channels.

        Returns:
            A mapping of ``{sensor_channel_id: flowrate_value}``.
        """
        pass

    @abstractmethod
    def get_sensor_unit(self,param_list: Optional[Sequence[int]] = None) -> Dict[int, str]:
        """Return sensor units for selected or all sensor channels.

        Args:
            param_list: Optional sequence of sensor channel IDs to query. If
                ``None``, the implementation should return all configured
                sensor channels.

        Returns:
            A mapping of ``{sensor_channel_id: unit_string}``.
        """
        pass
