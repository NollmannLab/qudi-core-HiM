# -*- coding: utf-8 -*-
"""
Interface for filter-wheel hardware used by qudi-core-HiM.

The hardware drivers in this repository expose the same minimal contract:

- report the current filter position
- move the wheel to a target position
- return a dictionary describing the available filters

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


class FilterWheelInterface(Base):
    """Interface for hardware drivers controlling a motorized filter wheel."""

    @abstractmethod
    def get_position(self):
        """Return the current filter-wheel position as an integer."""
        pass

    @abstractmethod
    def set_position(self, target_position):
        """Move the filter wheel to the requested position.

        Args:
            target_position: Desired filter position, usually counted from 1.

        Returns:
            An integer status code where ``0`` indicates success.
        """
        pass

    @abstractmethod
    def get_filter_dict(self):
        """Return metadata for all filters indexed by filter label."""
        pass
