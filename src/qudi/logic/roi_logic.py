# -*- coding: utf-8 -*-
"""
Author: F.Barho - adapted for qudi-core-HiM by JB Fiche
Created: 2020-11 -> translated into qudi-core-HiM on 2026-04-16
This module contains the ROI selection logic.

It is in large parts inspired and adapted from the Qudi poimanager logic.
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

# src/qudi/logic/roi_logic.py

from qtpy import QtCore
from qudi.core.module import LogicBase
from qudi.core.connector import Connector
from qudi.core.statusvariable import StatusVar


class RoiLogic(LogicBase):
    stage = Connector(interface='DummyXYStage', name='stage')
    roi_list = StatusVar(name='roi_list', default=[])
    active_roi = StatusVar(name='active_roi', default=-1)

    sigRoiListChanged = QtCore.Signal(list)
    sigActiveRoiChanged = QtCore.Signal(int)
    sigStageMoved = QtCore.Signal(dict)

    def on_activate(self):
        self._stage = self.stage()
        self.sigRoiListChanged.emit(list(self.roi_list))
        self.sigActiveRoiChanged.emit(int(self.active_roi))

    def on_deactivate(self):
        pass

    def add_roi(self, name, x, y, z=0.0):
        roi = {
            'name': str(name),
            'x': float(x),
            'y': float(y),
            'z': float(z),
        }
        rois = list(self.roi_list)
        rois.append(roi)
        self.roi_list = rois
        self.sigRoiListChanged.emit(list(self.roi_list))

    def delete_roi(self, index):
        rois = list(self.roi_list)
        if 0 <= index < len(rois):
            del rois[index]
            self.roi_list = rois
            if self.active_roi >= len(rois):
                self.active_roi = -1
            self.sigRoiListChanged.emit(list(self.roi_list))
            self.sigActiveRoiChanged.emit(int(self.active_roi))

    def set_active_roi(self, index):
        if 0 <= index < len(self.roi_list):
            self.active_roi = int(index)
        else:
            self.active_roi = -1
        self.sigActiveRoiChanged.emit(int(self.active_roi))

    def move_stage_to_roi(self, index):
        if not (0 <= index < len(self.roi_list)):
            return
        roi = self.roi_list[index]
        pos = {'x': roi['x'], 'y': roi['y'], 'z': roi['z']}
        new_pos = self._stage.move_abs(pos)
        self.active_roi = int(index)
        self.sigActiveRoiChanged.emit(int(self.active_roi))
        self.sigStageMoved.emit(dict(new_pos))

    def get_stage_position(self):
        return self._stage.get_position()