# -*- coding: utf-8 -*-
"""
Author: JB Fiche - written for qudi-core-HiM with Claude code
Created: 2026-10-12

Interface for galvo-mirror hardware modules used by qudi-core-HiM.

A galvo mirror is positioned by a single control voltage (e.g. the beam-sweep galvo of the OPM
microscope). This interface exposes that voltage, its allowed range and a safe rest position. All
voltages are in volts (V).

Error handling follows the qudi-core-HiM convention: a refused or failed command logs an error and
returns False (nothing is raised at run time); True means the command succeeded.

-----------------------------------------------------------------------------------
qudi-core is free software: you can redistribute it and/or modify it under the terms of the GNU General Public License
as published by the Free Software Foundation, either version 3 of the License, or (at your option) any later version.

Qudi is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU General Public License for more details.

You should have received a copy of the GNU General Public License along with Qudi. If not, see <http://www.gnu.org/licenses/>.
-----------------------------------------------------------------------------------

Modified for qudi-core-HiM (2026-10-12, Modified with Claude code): new file - GalvoInterface, the
  hardware contract for a voltage-positioned galvo mirror (set/get voltage, limits, rest position).
  set_voltage / go_to_rest return True/False (errors are logged, not raised).
"""

from abc import abstractmethod
from typing import Tuple

from qudi.core.module import Base


class GalvoInterface(Base):
    """Interface for a galvo mirror positioned by one control voltage (V)."""

    @abstractmethod
    def set_voltage(self, voltage: float) -> bool:
        """Move the galvo by writing the control voltage, in V.

        Returns True if the voltage was written. A voltage outside get_limits() is refused: log an
        error, write nothing, return False. A failed hardware write also logs and returns False.
        """
        pass

    @abstractmethod
    def get_voltage(self) -> float:
        """Return the last control voltage written, in V (an analog output cannot be read back)."""
        pass

    @abstractmethod
    def get_limits(self) -> Tuple[float, float]:
        """Return the allowed control-voltage range (minimum, maximum), in V."""
        pass

    @abstractmethod
    def get_rest_voltage(self) -> float:
        """Return the safe rest voltage, in V."""
        pass

    @abstractmethod
    def go_to_rest(self) -> bool:
        """Move the galvo to its rest voltage. Returns True on success, False otherwise."""
        pass
