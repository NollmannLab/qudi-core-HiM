# -*- coding: utf-8 -*-
"""
Author: JB Fiche with codex - adapted for qudi-core-HiM from the previous daq script used in qudi-HiM
Created: 2026-07-21

Interface for laser-control modules used by qudi-core-HiM.

The concrete drivers in this repository expose the same contract:

- report the nominal wavelengths controlled by the device
- store or apply intensity values for one selected laser line
- enable or disable all laser lines together
- put the device in a ready state before enabling output
- toggle external TTL control when supported

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


class LaserControlInterface(Base):
    """Interface for hardware or interfuse-hardware modules controlling lasers."""

    @abstractmethod
    def get_available_wavelengths(self) -> tuple[int, ...]:
        """Return the nominal wavelengths supported by the device."""
        pass

    @abstractmethod
    def update_line_intensity(self, wavelength, intensity):
        """Update the cached intensity state for one laser line."""
        pass

    @abstractmethod
    def apply_line_intensity(self, wavelength, intensity):
        """Update and immediately apply the intensity of one laser line."""
        pass

    @abstractmethod
    def ensure_ready(self):
        """Prepare the laser source for controlled output if required."""
        pass

    @abstractmethod
    def enable_all_lines(self):
        """Enable all configured laser lines using the stored intensity values."""
        pass

    @abstractmethod
    def disable_all_lines(self):
        """Disable all configured laser lines without clearing stored intensities."""
        pass

    @abstractmethod
    def set_ttl(self, ttl_state):
        """Enable or disable external TTL control."""
        pass
