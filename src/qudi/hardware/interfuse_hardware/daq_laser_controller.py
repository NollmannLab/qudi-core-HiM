# -*- coding: utf-8 -*-
"""
Author: JB Fiche - adapted for qudi-core-HiM from the previous daq script used in qudi-HiM
Created: 2026-07-21

Interfuse to control the laser using a DAQ or an FPGA device.

-----------------------------------------------------------------------------------
qudi-core is free software: you can redistribute it and/or modify it under the terms of the GNU General Public License
as published by the Free Software Foundation, either version 3 of the License, or (at your option) any later version.

Qudi is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU General Public License for more details.

You should have received a copy of the GNU General Public License along with Qudi. If not, see <http://www.gnu.org/licenses/>.
-----------------------------------------------------------------------------------
"""

from qudi.core.configoption import ConfigOption
from qudi.core.connector import Connector
from qudi.interface.laser_control_interface import LaserControlInterface


class DaqLaserController(LaserControlInterface):
    """Expose named DAQ outputs as a laser controller.

    Configuration structure:

    - ``laser_channels`` is a mapping keyed by wavelength, for example::

          laser_channels:
            405:
              daq_task: 'laser_405'
            488:
              daq_task: 'laser_488'

    Internal state structure:

    - ``_laser_dict`` is a mapping keyed by wavelength (``int``).
    - each value is a dictionary with the following keys:
      - ``channel``: a copy of the configuration dictionary for that wavelength
      - ``voltage``: last computed output voltage as ``float``
      - ``enabled``: ``bool`` indicating whether the channel is currently active

    Typical parameters are:

        daq_laser:
            module.Class: 'interfuse_hardware.daq_laser_controller.DaqLaserController'
            connect:
                daq: 'dummy_daq'
            options:
              laser_channels:
                405:
                  daq_task: 'laser_405'
                488:
                  daq_task: 'laser_488'
                561:
                  daq_task: 'laser_561'
                640:
                  daq_task: 'laser_640'

    """

    daq = Connector(name="daq", interface="DaqInterface")
    _laser_channels = ConfigOption("laser_channels", missing="error")

    # attributes
    _daq = None
    _laser_dict = {}

    def on_activate(self):
        """Connect to the DAQ backend and build the per-wavelength state dictionary.

        The resulting ``_laser_dict`` is keyed by wavelength and stores the copied
        channel configuration, the last computed voltage and the enabled state.
        """

        # connect to daq
        self._daq = self.daq()

        # initialize wavelengths list for the logic
        self._laser_dict = {
            int(wavelength): {
                "channel": dict(channel_config),
                "voltage": 0.0,
                "enabled": False
            }
            for wavelength, channel_config in self._laser_channels.items()
        }
        self._validate_laser_channels()

        # Ensure safe initial state.
        self.disable_all_lines()

    def on_deactivate(self):
        """Switch all outputs off and drop the DAQ connection."""
        self.disable_all_lines()
        self._daq = None

# ----------------------------------------------------------------------------------------------------------------------
# DAQ / laser controller / logic communication methods
# ----------------------------------------------------------------------------------------------------------------------

    def get_available_wavelengths(self) -> tuple[int, ...]:
        """Return the nominal wavelengths controlled through the DAQ.

        Returns:
            Tuple of wavelength keys used by ``_laser_dict`` and the public logic.
        """
        return tuple(self._laser_dict)

    def update_line_intensity(self, wavelength, intensity):
        """Update the cached voltage for one laser line.

        Args:
            wavelength: Wavelength key present in ``_laser_dict``.
            intensity: Requested output in percent of the configured maximum.

        The method stores the converted voltage in ``_laser_dict[wavelength]['voltage']``
        without writing to the DAQ.
        """
        voltage = self._convert_intensity_to_voltage(wavelength, intensity)
        self._laser_dict[wavelength]["voltage"] = voltage

    def apply_line_intensity(self, wavelength, intensity):
        """Update one laser line and immediately write the voltage to the DAQ.

        Args:
            wavelength: Wavelength key present in ``_laser_dict``.
            intensity: Requested output in percent of the configured maximum.

        This updates the cached voltage, marks the channel enabled, and writes the
        corresponding analog output to the configured DAQ task.
        """
        self.update_line_intensity(wavelength, intensity)
        self._laser_dict[wavelength]['enabled'] = True
        voltage = self._laser_dict[wavelength]['voltage']
        channel_config = self._laser_dict[wavelength]['channel']
        self._daq.write_named_ao(channel_config["daq_task"], voltage)

    def ensure_ready(self):
        """Prepare the DAQ backend for use.

        The DAQ implementation does not need a dedicated warm-up step, so this is
        intentionally a no-op.
        """
        pass

    def enable_all_lines(self):
        """Enable every configured laser line using the cached voltages.

        Channels with a cached voltage of zero are marked enabled but do not produce
        an analog output update.
        """
        for wavelength, channel_state in self._laser_dict.items():
            voltage = self._laser_dict[wavelength]['voltage']
            self._laser_dict[wavelength]['enabled'] = True
            if voltage > 0:
                channel_config = self._laser_dict[wavelength]['channel']
                self._daq.write_named_ao(channel_config["daq_task"], voltage)

    def disable_all_lines(self):
        """Disable all laser lines without clearing cached voltages.

        The ``voltage`` entries in ``_laser_dict`` are preserved so the previous
        settings can be restored later.
        """
        for wavelength in self._laser_dict:
            self._laser_dict[wavelength]['enabled'] = False
            channel_config = self._laser_dict[wavelength]['channel']
            self._daq.write_named_ao(channel_config["daq_task"], 0)

    def set_ttl(self, ttl_state):
        """Set TTL control if supported by the backend.

        The DAQ/FPGA implementation currently does not expose a separate TTL mode,
        so this is a no-op.
        """
        pass


# ----------------------------------------------------------------------------------------------------------------------
# Private methods
# ----------------------------------------------------------------------------------------------------------------------

    def _validate_laser_channels(self) -> None:
        """Validate the wavelength keys and required DAQ-task mapping.

        Expected structure of each entry in ``_laser_dict``:

        - key: wavelength as a positive ``int``
        - value: dictionary containing a ``channel`` mapping with at least
          ``daq_task``
        """
        if not self._laser_dict:
            raise ValueError("No DAQ-controlled laser channels are configured.")

        for wavelength, property in self._laser_dict.items():
            if wavelength <= 0:
                raise ValueError(f"Invalid laser wavelength: {wavelength!r}.")

            channel_config = property['channel']
            if not isinstance(channel_config, dict):
                raise TypeError(
                    f"Configuration for {wavelength} nm must be a dictionary."
                )

            daq_task = channel_config.get("daq_task")

            if not daq_task:
                raise ValueError(
                    f"No DAQ task is configured for the {wavelength} nm laser."
                )

    def _get_voltage_range(self, wavelength):
        """Return the maximum voltage supported by the configured DAQ task."""
        channel_config = self._laser_dict[wavelength]["channel"]
        task_name = channel_config["daq_task"]
        task_voltage_range = self._daq.get_task_range(task_name)
        return max(task_voltage_range)

    def _convert_intensity_to_voltage(self, wavelength, intensity):
        """Convert an intensity percentage into a DAQ voltage."""
        max_voltage = self._get_voltage_range(wavelength)
        return float(intensity * max_voltage / 100)
