# -*- coding: utf-8 -*-
"""
Author: JB Fiche - adapted for qudi-core-HiM
Created: 2021-06-24 -> translated into qudi-core-HiM on 2026-06-12

This module contains a class representing a Lumencor celesta laser source.

-----------------------------------------------------------------------------------
qudi-core is free software: you can redistribute it and/or modify it under the terms of the GNU General Public License
as published by the Free Software Foundation, either version 3 of the License, or (at your option) any later version.

Qudi is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU General Public License for more details.

You should have received a copy of the GNU General Public License along with Qudi. If not, see <http://www.gnu.org/licenses/>.
-----------------------------------------------------------------------------------
"""
import urllib.request
from qudi.core.configoption import ConfigOption
from qudi.interface.laser_control_interface import LaserControlInterface
from time import sleep


class LumencorCelesta(LaserControlInterface):
    """Class representing the Lumencor Celesta laser source.

    Configuration structure:

    - ``wavelengths_nm`` is a list of integer nominal wavelengths supported by the
      source, for example::

          wavelengths_nm:
            - 405
            - 477
            - 546
            - 638

    Internal state structure:

    - ``_laser_dict`` is a mapping keyed by wavelength (``int``).
    - each value is a dictionary with:
      - ``enabled``: ``0`` or ``1`` depending on the source state
      - ``intensity``: cached intensity value, stored in Celesta units

    Example config for copy-paste:

          celesta:
            module.Class: 'laser.lumencor_celesta.LumencorCelesta'
            options:
              ip: '192.168.201.200'
              wavelengths_nm:
                - 405
                - 477
                - 546
                - 638
                - 750
    """

    # config options
    _ip = ConfigOption('ip', missing='error')
    _wavelengths = ConfigOption('wavelengths_nm', missing='error', converter=list)

    # attributes
    _laser_dict = {}

    def on_activate(self):
        """Initialize the device, validate the wavelength list, and build ``_laser_dict``.

        The created ``_laser_dict`` is keyed by wavelength and stores the enabled
        state plus the cached intensity for each source line.
        """

        # retrieve available wavelengths from config
        wavelengths = self.get_available_wavelengths()

        if not wavelengths:
            raise ValueError("No Celesta wavelengths are configured.")

        if len(wavelengths) != len(set(wavelengths)):
            raise ValueError("Celesta wavelengths must be unique.")

        # create dictionary to hold laser wavelengths, intensities and states
        self._laser_dict = {
            wavelength: {
                "enabled": 0,
                "intensity": 0.0,
            }
            for wavelength in wavelengths
        }

        # test communication
        try:
            message = self._send_httpcommand(self._ip, 'GET VER')
            self.log.info(f"Lumencor source version {message['message']} was found")
        except Exception as e:
            self.log.error(f"Lumencor init failed: {e}")

    def on_deactivate(self):
        """Disable all output and put the source back into a safe state."""
        self.disable_all_lines()
        self.set_ttl(False)

# ----------------------------------------------------------------------------------------------------------------------
# Celesta status functions
# ----------------------------------------------------------------------------------------------------------------------

    def _status(self):
        """Query and return the Celesta status string.

        The returned value is the raw status message from the device, for example
        ``A STAT 0`` for normal operation or ``A STAT 7`` for standby.
        """
        message = self._send_httpcommand(self._ip, 'GET STAT')
        status = message['message']

        if status.find('A STAT') == -1:
            self.log.warning('Communication with the Celesta is currently impossible')
        elif status == 'A STAT 1' or status == 'A STAT 2' or status == 'A STAT 3':
            self.log.warning('There is an issue with the celesta source : overheating')
        return status

    def _wakeup(self):
        """Wake the source from standby and wait until it becomes ready."""
        self._send_httpcommand(self._ip, 'WAKEUP')
        sleep(.1)
        status = self._status()

        if status == "A STAT 7":
            self.log.warning('Celesta was in stand-by mode. Launching warming-up procedure ... wait a few seconds')
            while status == 'A STAT 7':
                sleep(0.5)
                status = self._status()
            self.log.info('Celesta laser source is ready!')

# ----------------------------------------------------------------------------------------------------------------------
# Lasercontrol interface methods for logic - hardware communication
# ----------------------------------------------------------------------------------------------------------------------

    def get_available_wavelengths(self) -> tuple[int, ...]:
        """Return the nominal wavelengths physically available from the source."""
        return tuple(int(wavelength) for wavelength in self._wavelengths)

    def update_line_intensity(self, wavelength, intensity):
        """Update the cached Celesta intensity for one wavelength.

        Args:
            wavelength: Wavelength key present in ``_laser_dict``.
            intensity: Requested output in percent.

        The value is converted to the Celesta's internal units and stored in
        ``_laser_dict[wavelength]['intensity']``. The device is updated for all
        channels after the cache change.
        """
        self._laser_dict[wavelength]["intensity"] = int(intensity * 10)
        self._set_intensity_all_channels()

    def apply_line_intensity(self, wavelength, intensity):
        """Update one line and immediately apply the new enabled state to the source."""
        self.update_line_intensity(wavelength, intensity)
        if intensity > 0:
            self._laser_dict[wavelength]["enabled"] = 1
        else:
            self._laser_dict[wavelength]["enabled"] = 0

        self._set_state_all_channels()

    def ensure_ready(self):
        """Ensure the source is awake and ready for controlled output."""
        self._wakeup()

    def enable_all_lines(self):
        """Enable all channels that currently have a non-zero intensity."""
        for wavelength, channel_state in self._laser_dict.items():
            if (channel_state['intensity'] > 0) and (channel_state['enabled'] == 0):
                self._laser_dict[wavelength]['enabled'] = 1
        self._set_state_all_channels()

    def disable_all_lines(self):
        """Disable all laser lines without clearing the cached intensities."""
        for wavelength in self._laser_dict:
            self._laser_dict[wavelength]['enabled'] = 0
        self._set_state_all_channels()

    def set_ttl(self, ttl_state):
        """Enable or disable TTL control on the Celesta source.

        Args:
            ttl_state: ``True`` enables external TTL control, ``False`` disables it.
        """
        if ttl_state:
            self._send_httpcommand(self._ip, 'SET TTLENABLE 1')
            self._send_httpcommand(self._ip, 'SET TTLPOL POS')
        else:
            self._send_httpcommand(self._ip, 'SET TTLENABLE 0')

# ----------------------------------------------------------------------------------------------------------------------
# Private getter / setter methods
# ----------------------------------------------------------------------------------------------------------------------

    def _send_httpcommand(self, ip, command):
        """Send an HTTP command to the Celesta and return the parsed response."""
        command_full = f"http://{ip}/service/?command={urllib.parse.quote(command)}"
        with urllib.request.urlopen(command_full) as response:
            message = eval(response.read())  # the default is conveniently JSON so eval creates dictionary
            if message['message'][0] == 'E':
                self.log.warning('An error occurred - the command was not recognized')

        return message

    def _set_intensity_all_channels(self):
        """Send the cached intensity values for all wavelengths to the source."""
        intensities = [self._laser_dict[wavelength]['intensity']
                       for wavelength in self._laser_dict]
        command = 'SET MULCHINT {}'.format(' '.join(map(str, intensities)))
        self._send_httpcommand(self._ip, command)

    def _set_state_all_channels(self):
        """Send the cached enabled states for all wavelengths to the source."""
        enabled_states = [self._laser_dict[wavelength]['enabled']
                       for wavelength in self._laser_dict]
        command = 'SET MULCH {}'.format(' '.join(map(str, enabled_states)))
        self._send_httpcommand(self._ip, command)

    def _get_laserline_intensity(self):
        """Query and return the intensity of all laser lines as a list of integers."""
        message = self._send_httpcommand(self._ip, 'GET MULCHINT')
        intensity = [int(s) for s in message['message'].split() if s.isdigit()]

        return intensity

    def _get_laserline_state(self):
        """Query and return the state of all laser lines as a list of integers."""
        message = self._send_httpcommand(self._ip, 'GET MULCH')
        status = [int(s) for s in message['message'].split() if s.isdigit()]

        return status
