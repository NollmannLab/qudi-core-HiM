# -*- coding: utf-8 -*-
"""
Author: F.Barho - adapted for qudi-core-HiM by JB Fiche
Created: 2020-11 -> translated into qudi-core-HiM on 2026-04-22
This module contains the interface for the translation stage used to define the ROIs.

It is in large parts inspired and adapted from the Qudi roi_manager logic.
(+in this version: deactivated tools concerning the camera image overlay but would be interesting to establish this in
the future)

ROIs are regrouped into an ROI list (instead of using the terminology of POI in ROI or, as in the labview measurement
software ROIs per embryo.) The chosen nomenclature is more flexible than regrouping by embryo and can be extended to other
types of samples.
-----------------------------------------------------------------------------------
qudi-core is free software: you can redistribute it and/or modify it under the terms of the GNU General Public License
as published by the Free Software Foundation, either version 3 of the License, or (at your option) any later version.

Qudi is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU General Public License for more details.

You should have received a copy of the GNU General Public License along with Qudi. If not, see <http://www.gnu.org/licenses/>.
-----------------------------------------------------------------------------------
"""

from abc import abstractmethod
from typing import Dict, List, Optional
from qudi.core.module import Base


class MultiAxisStageInterface(Base):
    """Interface for a motorized stage exposing one or more independent axes.

    Hardware implementations may provide translation and/or rotation axes. Axis
    labels and units are declared by :meth:`get_constraints`, and all movement,
    position, status, and velocity dictionaries are indexed by those labels.

    Linear hardware used in the HiM setup should expose positions in micrometres
    and velocities in micrometres per second. Rotational hardware should expose
    positions in degrees and velocities in degrees per second.

    Every axis constraint dictionary must contain the following keys::

        {
            'label': str,
            'type': 'linear' or 'rotation',
            'unit': 'um' or 'degree',
            'velocity_unit': 'um/s' or 'degree/s',
            'ramp': list or None,
            'pos_min': float or None,
            'pos_max': float or None,
            'pos_step': float or None,
            'max_step': float or None,
            'vel_min': float or None,
            'vel_max': float or None,
            'vel_step': float or None,
            'acc_min': float or None,
            'acc_max': float or None,
            'acc_step': float or None,
        }
    """

    @abstractmethod
    def get_constraints(self) -> Dict[str, dict]:
        """Return the constraints of all configured axes.

        :return: Constraint dictionaries indexed by axis label.
        :rtype: dict
        """
        pass

    @abstractmethod
    def move_rel(self, param_dict: Dict[str, float]) -> bool:
        """Move selected axes by relative distances or angles.

        Values use the position unit declared for each axis in
        :meth:`get_constraints`.

        :param dict param_dict: Relative movement indexed by axis label.
        :return: ``True`` if at least one movement command was accepted.
        :rtype: bool
        """
        pass

    @abstractmethod
    def move_abs(self, param_dict: Dict[str, float]) -> bool:
        """Move selected axes to absolute positions or angles.

        Values use the position unit declared for each axis in
        :meth:`get_constraints`.

        :param dict param_dict: Absolute target indexed by axis label.
        :return: ``True`` if at least one movement command was accepted.
        :rtype: bool
        """
        pass

    @abstractmethod
    def abort(self) -> bool:
        """Abort movement of all configured axes.

        :return: ``True`` if the abort command was handled successfully.
        :rtype: bool
        """
        pass

    @abstractmethod
    def get_pos(self, param_list: Optional[List[str]] = None) -> Dict[str, float]:
        """Return current positions of selected axes.

        :param list param_list: Optional axis labels. All configured axes are
            returned when omitted.
        :return: Current positions indexed by axis label.
        :rtype: dict
        """
        pass

    @abstractmethod
    def get_status(self, param_list: Optional[List[str]] = None) -> Dict[str, bool]:
        """Return on-target states of selected axes.

        ``True`` means that the corresponding axis is idle/on target, while
        ``False`` means that it is moving or not on target.

        :param list param_list: Optional axis labels. All configured axes are
            returned when omitted.
        :return: On-target states indexed by axis label.
        :rtype: dict
        """
        pass

    @abstractmethod
    def calibrate(self, param_list: Optional[List[str]] = None) -> int:
        """Run the hardware-specific calibration for selected axes.

        :param list param_list: Optional axis labels. All configured axes are
            calibrated when omitted.
        :return: ``0`` if at least one requested calibration was accepted,
            otherwise ``-1``.
        :rtype: int
        """
        pass

    @abstractmethod
    def get_velocity(self, param_list: Optional[List[str]] = None) -> Dict[str, float]:
        """Return current velocities of selected axes.

        Values use the velocity unit declared for each axis in
        :meth:`get_constraints`.

        :param list param_list: Optional axis labels. All configured axes are
            returned when omitted.
        :return: Velocities indexed by axis label.
        :rtype: dict
        """
        pass

    @abstractmethod
    def set_velocity(self, param_dict: Dict[str, float]) -> int:
        """Set velocities of selected axes.

        Values use the velocity unit declared for each axis in
        :meth:`get_constraints`.

        :param dict param_dict: Target velocities indexed by axis label.
        :return: ``0`` if at least one velocity command was accepted,
            otherwise ``-1``.
        :rtype: int
        """
        pass

    @abstractmethod
    def wait_for_idle(self) -> bool:
        """Wait until all configured axes are idle or a timeout occurs.

        :return: ``True`` when the stage becomes idle, or ``False`` after a
            timeout or communication failure.
        :rtype: bool
        """
        pass