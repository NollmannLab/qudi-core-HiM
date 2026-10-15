# -*- coding: utf-8 -*-
"""
Logic module for the bright-field illumination (LED).

Thin logic layer over a hardware module implementing BrightfieldInterface (ASI Tiger / MS2000 LED output), used by
the basic imaging GUI and by tasks. Intensities are in percent of the maximum LED power; the hardware clamps the
value to its supported range.

-----------------------------------------------------------------------------------
qudi-core is free software: you can redistribute it and/or modify it under the terms of the GNU General Public License
as published by the Free Software Foundation, either version 3 of the License, or (at your option) any later version.

Qudi is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU General Public License for more details.

You should have received a copy of the GNU General Public License along with Qudi. If not, see <http://www.gnu.org/licenses/>.
-----------------------------------------------------------------------------------
"""

from qtpy import QtCore

from qudi.core.connector import Connector
from qudi.core.module import LogicBase


class BrightfieldLogic(LogicBase):
    """Switch the bright-field LED on / off and set its intensity.

    The stored intensity is applied when the LED is switched on and, while it is on, every time it is updated.
    All commands return True on success and False if the hardware refused the command (the reason is logged as an
    error). sigBrightfieldStopped is emitted whenever the LED is switched off, so that the GUI can reset its
    controls when the LED is stopped programmatically (task preparation, deactivation).

    Config example for copy-paste:

        brightfield_logic:
            module.Class: 'brightfield_logic.BrightfieldLogic'
            connect:
                brightfield: 'tiger'
    """
    brightfield = Connector(name='brightfield', interface='BrightfieldInterface')

    sigBrightfieldStopped = QtCore.Signal()

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._brightfield = None
        self._enabled = False
        self._intensity = 0.0

    def on_activate(self):
        """Connect the hardware. The LED state is considered off until it is switched on from this module."""
        self._brightfield = self.brightfield()
        self._enabled = False

    def on_deactivate(self):
        """Switch the LED off."""
        self.led_off()

    @property
    def enabled(self) -> bool:
        """True while the LED is switched on."""
        return self._enabled

    @property
    def intensity(self) -> float:
        """Stored LED intensity (percent)."""
        return self._intensity

    @QtCore.Slot(float)
    def led_control(self, intensity) -> bool:
        """Store the intensity and switch the LED on with it.

        :param float intensity: LED intensity in percent.
        :return: True if the hardware accepted the command. On failure the LED is considered off and
                 sigBrightfieldStopped is emitted so that the GUI controls are reset.
        """
        self._intensity = float(intensity)
        if not self._set_hardware_intensity(self._intensity):
            if not self._enabled:
                self.sigBrightfieldStopped.emit()
            return False
        self._enabled = True
        return True

    @QtCore.Slot()
    def led_off(self) -> bool:
        """Switch the LED off (intensity 0 on the hardware; the stored intensity is kept) and emit
        sigBrightfieldStopped.

        :return: True if the hardware accepted the command. On failure the state is left unchanged.
        """
        if not self._set_hardware_intensity(0):
            return False
        self._enabled = False
        self.sigBrightfieldStopped.emit()
        return True

    @QtCore.Slot(float)
    def update_intensity(self, intensity) -> bool:
        """Store the intensity and apply it to the hardware only if the LED is on.

        :param float intensity: LED intensity in percent.
        :return: True if stored (and applied when the LED is on), False if the hardware refused the command.
        """
        self._intensity = float(intensity)
        if not self._enabled:
            return True
        return self._set_hardware_intensity(self._intensity)

    def stop_brightfield_output(self) -> bool:
        """Switch the LED off if it is on (for example before a task starts).

        :return: True if the LED is off afterwards.
        """
        if self._enabled:
            return self.led_off()
        return True

    def _set_hardware_intensity(self, intensity) -> bool:
        """Send the intensity to the hardware; log an error and return False if the command is refused."""
        try:
            ok = self._brightfield.led_control(intensity)
        except Exception as err:
            self.log.error(f'Could not set the bright-field LED intensity to {intensity}: {err}')
            return False
        if not ok:
            self.log.error(f'The bright-field hardware refused the LED intensity {intensity}.')
            return False
        return True
