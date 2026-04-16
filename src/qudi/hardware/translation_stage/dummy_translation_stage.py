# -*- coding: utf-8 -*-

"""
# Author: JB Fiche (from original F.Barho)
# Created: 2026-04-16
# This file contains the dummy for a motorized XY translation stage interface.

qudi-core is free software: you can redistribute it and/or modify it under the terms of the GNU General Public License
as published by the Free Software Foundation, either version 3 of the License, or (at your option) any later version.

Qudi is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU General Public License for more details.

You should have received a copy of the GNU General Public License along with Qudi. If not, see <http://www.gnu.org/licenses/>.
"""
from qudi.core.module import Base
from qudi.core.configoption import ConfigOption
import time


class DummyXYStage(Base):
    _x_min = ConfigOption(name='x_min', default=0.0)
    _x_max = ConfigOption(name='x_max', default=100000.0)
    _y_min = ConfigOption(name='y_min', default=0.0)
    _y_max = ConfigOption(name='y_max', default=100000.0)
    _z_min = ConfigOption(name='z_min', default=0.0)
    _z_max = ConfigOption(name='z_max', default=1000.0)

    def on_activate(self):
        self._position = {'x': 0.0, 'y': 0.0, 'z': 0.0}

    def on_deactivate(self):
        pass

    def get_position(self):
        return dict(self._position)

    def move_abs(self, pos):
        for axis in ('x', 'y', 'z'):
            if axis in pos:
                self._position[axis] = float(pos[axis])
        return self.get_position()

    def move_rel(self, delta):
        for axis in ('x', 'y', 'z'):
            if axis in delta:
                self._position[axis] += float(delta[axis])
        return self.get_position()

    def get_constraints(self):
        return {
            'x': (self._x_min, self._x_max),
            'y': (self._y_min, self._y_max),
            'z': (self._z_min, self._z_max),
        }