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
from qudi.core.module import Base


class RoiStageInterface(Base):
    """Minimal stage interface for ROI management."""

    @abstractmethod
    def get_constraints(self):
        """Return axis constraints, e.g. limits and available axes."""
        pass

    @abstractmethod
    def move_abs(self, pos):
        """Move to an absolute position given as a dict."""
        pass

    @abstractmethod
    def move_rel(self, delta):
        """Move by a relative offset given as a dict."""
        pass

    @abstractmethod
    def abort(self):
        """ Abort current action or movement """
        pass

    @abstractmethod
    def get_pos(self, param_list=None):
        """ Get current position of the stage arms"""
        pass

    @abstractmethod
    def get_status(self, param_list=None):
        """ Get current status of the stage """
        pass

    @abstractmethod
    def calibrate(self, param_list=None):
        """ optional : if required calibrate an axis of the stage """
        pass

    @abstractmethod
    def get_velocity(self, param_list=None):
        """ Get current setting for the velocity of one of the axis arm """
        pass

    @abstractmethod
    def set_velocity(self, param_dict=None):
        """ Set the velocity """
        pass

    @abstractmethod
    def wait_for_idle(self):
        """ Set a delay between two successive commands"""
        pass

    def _make_wait_after_movement(self):
        """ Set a delay after a movement """
        pass