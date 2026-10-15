# -*- coding: utf-8 -*-
"""
Interface for hardware controlling a bright-field illumination source (LED).

Implemented by the ASI stage controllers (Tiger, MS2000) that drive the optional bright-field LED.

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


class BrightfieldInterface(Base):
    """Interface for hardware driving a bright-field LED."""

    @abstractmethod
    def led_control(self, intensity):
        """Set the LED intensity.

        :param intensity: LED intensity in percent of the maximum (0 switches the LED off). The hardware clamps
                          the value to its supported range.
        :return: True if the command was accepted, False otherwise.
        """
        pass
