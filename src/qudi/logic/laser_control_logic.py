# -*- coding: utf-8 -*-
"""
Author: F. Barho. Adapted to qudi-core by JB Fiche with chatGPT.
Created 2021-02-10 -> Reformatted 2026-08-01.

A module to control the lasers via a DAQ (analog output and digital output line for triggering), via an FPGA
or using the Lumencor celesta. The DAQ / FPGA are used to control the AOTF to select the laser wavelength.

-----------------------------------------------------------------------------------
qudi-core is free software: you can redistribute it and/or modify it under the terms of the GNU General Public License
as published by the Free Software Foundation, either version 3 of the License, or (at your option) any later version.

Qudi is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU General Public License for more details.

You should have received a copy of the GNU General Public License along with Qudi. If not, see <http://www.gnu.org/licenses/>.
-----------------------------------------------------------------------------------
"""

from copy import deepcopy

from time import sleep

from qudi.core.module import LogicBase
from qudi.core.connector import Connector
from qudi.core.configoption import ConfigOption
from qtpy import QtCore

# ======================================================================================================================
# Logic class
# ======================================================================================================================

class LaserControlLogic(LogicBase):
    """ This class combines all the methods for controlling the laser illumination and synchronization with the camera.
    It calls for a controller, which is either a hardware (FPGA, DAQ, CELESTA) or a logic combining two hardwares (FPGA
    + CELESTA).

    Example config for copy-paste:
        lasercontrol_logic:
        module.Class: 'lasercontrol_logic.LaserControlLogic'
        controllertype: 'daq'
        connect:
            controller: 'dummy_daq'
    """
    # declare connectors for the laser and the filter wheel. The filter wheel is required to handle laser lines permission depending on the
    # selected emission filter. If no filter wheel is used, a dummy filter wheel is defined holding a single filter.
    laser = Connector(name='laser', interface='LaserControlInterface')
    filter_wheel = Connector(name='filter_wheel', interface='FilterWheelInterface')
    optical_path = ConfigOption('optical_path', missing='error')

    # signals
    sigIntensityChanged = QtCore.Signal()  # if intensity dict is changed programmatically, this updates the GUI
    sigLaserStopped = QtCore.Signal()
    sigDisableLaserActions = QtCore.Signal()
    sigEnableLaserActions = QtCore.Signal()

    # private attributes
    _laser = None
    _filter_wheel = None
    allowed_wavelengths_nm = []
    dichroic = ""
    intensity_dict = {}
    laser_dict = {}
    filter_dict = {}
    _enabled = False


    def on_activate(self):
        """ Initialisation performed during activation of the module.
        """

        # instantiate hardware
        self._laser = self.laser()
        self._filter_wheel = self.filter_wheel()
        self.enabled = False  # attribute to handle the on-off switching of the laser-on button

        # get optical path parameters
        self.allowed_wavelengths_nm = self.optical_path['dichroic_allowed_wavelengths_nm']
        self.dichroic = self.optical_path['dichroic_ref']

        # get filter parameters
        if self._filter_wheel is not None:
            self.filter_dict = self._filter_wheel.get_filter_dict()
        else:
            self.log.error("No filter wheel connected - if no filter wheel is used for the setup, please define a dummy "
                           "with the filter used for the experiment")

        # create the wavelengths dictionary
        available_wavelengths = self._laser.get_available_wavelengths()
        allowed_wavelengths = {
            int(wavelength)
            for wavelength in self.allowed_wavelengths_nm
        }

        self.laser_dict = {
            wavelength: {
                "allowed": wavelength in allowed_wavelengths,
                "intensity": 0.0,
            }
            for wavelength in available_wavelengths
        }

    def on_deactivate(self):
        """ Perform required deactivation. """
        self.stop_all()
        self.reset_laser_intensities()

# ----------------------------------------------------------------------------------------------------------------------
# Methods to access the laser dictionary from hardware and to access and modify the intensity dictionary
# ----------------------------------------------------------------------------------------------------------------------

    @property
    def laser_state(self) -> dict:
        """Return a copy of the current laser-line state.
        """
        return deepcopy(self.laser_dict)

    @property
    def laser_enabled(self) -> bool:
        """Return whether laser emission is currently enabled.
        """
        return self._enabled

    @QtCore.Slot(str, float)  # should the decorator be removed when this method is called in a task ???
    def update_intensity_dict(self, laser_name, value):
        """Update the intensity associated to the selected laser
        """
        self.laser_dict[laser_name]["intensity"] = value

    def set_laser_line_intensity(self, wavelength_nm: int, intensity_percent: float) -> None:
        """Set the requested intensity of one permitted laser line.
        """
        self._laser.set_intensity_selected_laser_line(wavelength_nm, intensity_percent)

    # def set_laser_intensities(self, intensities_dict: dict[int, float]) -> None:
    #     """Set several requested intensities after validating all entries.
    #     """
    #     self._laser.set_intensity_all_laser_lines(intensities_dict)

    @QtCore.Slot()
    def set_laser_enabled(self) -> None:
        """Enable or disable emission using the requested intensities."""
        self._enabled = True
        for wavelength_nm in self.laser_dict:
            intensity = self.laser_dict[wavelength_nm]["intensity"]
            if intensity > 0:
                self.set_laser_line_intensity(wavelength_nm, intensity)

    @QtCore.Slot()
    def stop_all(self) -> None:
        """Immediately disable all laser emission."""
        self._enabled = False
        for wavelength_nm in self.laser_dict:
            intensity = self.laser_dict[wavelength_nm]["intensity"]
            if intensity > 0:
                self.set_laser_line_intensity(wavelength_nm, 0)

    def reset_laser_intensities(self):
        """Set the intensity of all laser to zero"""
        for wavelength_nm in self.laser_dict:
            self.laser_dict[wavelength_nm]["intensity"] = 0
            self.sigIntensityChanged.emit()
            if self.laser_enabled:
                self.set_laser_line_intensity(wavelength_nm, 0)

    def set_external_trigger(self, enabled: bool) -> None:
        """Enable or disable external trigger control."""
        ...

# ----------------------------------------------------------------------------------------------------------------------
# Methods to access the laser dictionary from hardware and to access and modify the intensity dictionary
# ----------------------------------------------------------------------------------------------------------------------

    # def get_laser_dict(self):
    #     """ Retrieve the dictionary containing wavelength, channel, and voltage range from the hardware.
    #
    #     exemplary entry: {'laser1': {'label': 'laser1', 'wavelength': '405 nm', 'channel': '/Dev1/AO2',
    #                                 'voltage_range': [0, 10]}  # DAQ
    #                      {'laser1': {'label': 'laser1', 'wavelength': '405 nm', 'channel': '405'}}
    #                      # FPGA. 'channel' corresponds to the registername.
    #                     {'laser1': {'label': 'laser1', 'wavelength': '405 nm', 'channel': 1}}
    #                     # Lumencor. 'channel' corresponds to the address for communicating with the celesta source.
    #
    #     :return: dict laser_dict
    #     """
    #     return self._laser.get_dict()

    #
    # def reset_intensity_dict(self):
    #     """ Resets all values of the intensity_dict to zero.
    #     This method is for example called from filterwheel logic before setting a new filter.
    #     Emits a signal to inform the GUI about modified intensities.
    #
    #     :return: None
    #     """
    #     for key in self._intensity_dict:
    #         self._intensity_dict[key] = 0
    #     self.sigIntensityChanged.emit()

    # @QtCore.Slot(str, float)  # should the decorator be removed when this method is called in a task ???
    # def update_intensity_dict(self, key, value):
    #     """ DO NOT CALL THIS FUNCTION UNLESS YOU ARE SURE THAT THE FILTER YOU ARE USING IS ADAPTED FOR THE
    #     LASER LINE YOU WANT TO SET!
    #     This function updates the desired intensity value that is applied to the specified output.
    #     In case lasers are already on, the new value is automatically applied.
    #     Else, it just prepares the value that will be applied when voltage output is activated.
    #     As the GUI contains a security mechanism to avoid setting a value to a forbidden laser
    #     (incompatible with the current filter setting), there is no risk when updating intensities from the GUI.
    #     However when calling this method from the iPython console, make sure to activate only lasers that are allowed
    #     for the filter in the beam path.
    #
    #     :param: str key: identifier present in the intensity dict, typically 'laser1', 'laser2', ..
    #     :param: float value: new intensity value (0 - 100 %) to be applied to the specified laser line
    #
    #     :return: None
    #     """
    #     try:
    #         self._intensity_dict[key] = value
    #         # if laser is already on, the new value must be written to the daq output
    #         if self.enabled:
    #             self.apply_voltage()
    #     except KeyError:
    #         self.log.info('Specified identifier not available')

# ----------------------------------------------------------------------------------------------------------------------
# Methods to switch lasers on / off
# ----------------------------------------------------------------------------------------------------------------------

    # def apply_voltage(self):
    #     """ Apply the intensities defined in the _intensity_dict to the belonging channels.
    #
    #     This method is used to switch lasers on from the GUI, for this reason it iterates over all defined channels
    #     (no individual laser on / off button but one button for all).
    #
    #     :return: None
    #     """
    #     self.enabled = True
    #     # ('laser dict : {}'.format(self._laser_dict))
    #
    #     if self.controllertype == 'daq':
    #         for key in self._laser_dict:
    #             self._controller.apply_voltage(
    #                 self._intensity_dict[key] * self._laser_dict[key]['ao_voltage_range'][1] / 100,
    #                 self._laser_dict[key]['channel'])
    #             # conversion factor: user indicates values in percent of max voltage
    #     elif self.controllertype == 'fpga':
    #         for key in self._laser_dict:
    #             self._controller.apply_voltage(self._intensity_dict[key], self._laser_dict[key]['channel'])
    #     elif (self.controllertype == 'celesta') or (self.controllertype == 'celesta_fpga'):
    #         intensity, laser_on = self.lumencor_read_intensity_dict(self._intensity_dict)
    #         self._controller.apply_voltage(intensity, laser_on)
    #     else:
    #         self.log.warning('your controller type is currently not covered')

    def apply_voltage_single_channel(self, voltage, channel):
        """ This method makes the low level method from the hardware directly accessible.
        Write a voltage to the specified channel.

        :param: float voltage: voltage value to be applied
        :param: str channel: analog output line such as /Dev1/AO0

        :return: None
        """
        if self.controllertype == 'daq' or self.controllertype == 'fpga':
            self._controller.apply_voltage(voltage, channel)

    # def voltage_off(self):
    #     """ Switch all lasers off.
    #     The intensity dictionary is not reset, to be able to restart laser output right away.
    #     """
    #     self.enabled = False
    #     if (self.controllertype == 'daq') or (self.controllertype == 'fpga'):
    #         for key in self._laser_dict:
    #             self._controller.apply_voltage(0.0, self._laser_dict[key]['channel'])
    #     elif (self.controllertype == 'celesta') or (self.controllertype == 'celesta_fpga'):
    #         intensity, laser_on = self.lumencor_read_intensity_dict(self._intensity_dict)
    #         self._controller.apply_voltage(intensity, [x * 0 for x in laser_on])

# ----------------------------------------------------------------------------------------------------------------------
# Methods used in tasks for synchronization between lightsource and camera in external trigger mode
# ----------------------------------------------------------------------------------------------------------------------

# DAQ specific methods -------------------------------------------------------------------------------------------------

    def send_trigger(self):
        """ Send a sequence 0 - 1 - 0 to a digital output. Only applicable if connected device is a DAQ.
        :return None
        """
        if self.controllertype == 'daq':
            self._controller.send_trigger()
        else:
            pass

    def send_trigger_and_control_ai(self):
        """ Send a sequence 0 - 1 - 0 to a digital output, and control if the fire trigger sent by the camera
        was received. Only applicable if connected device is a DAQ.
        :return: None
        """
        if self.controllertype == 'daq':
            return self._controller.send_trigger_and_control_ai()
        else:
            pass

    def read_trigger_ai_channel(self):
        """ This method gives direct access to reading the trigger input. Read the fire trigger sent by the
        camera. Only applicable if connected device is a DAQ.
        :return: float ai_value: analog input signal read on the specified analog input.
        """
        if self.controllertype == 'daq':
            taskhandle = self._controller.trigger_read_taskhandle
            ai_value = self._controller.read_ai_channel(taskhandle)
            return ai_value
        else:
            pass

# FPGA specific methods ------------------------------------------------------------------------------------------------

    def close_default_session(self):
        """ This method is called before another bitfile than the default one shall be loaded. It closes the default
        session, where the default bitfile runs. Only applicable if connected device is a FPGA.
        :return: None
        """
        if (self.controllertype == 'fpga') or (self.controllertype == 'celesta_fpga'):
            self._controller.close_default_session()
        else:
            pass

    def restart_default_session(self):
        """ This method allows to restart the default FPGA session. Only applicable if connected device is a FPGA.
        :return: None
        """
        if (self.controllertype == 'fpga') or (self.controllertype == 'celesta_fpga'):
            self._controller.restart_default_session()
        else:
            pass

    def start_task_session(self, bitfile):
        """ Load a bitfile used for a specific task. Only applicable if connected device is FPGA or CELESTA_FPGA.
        :param: str bitfile: complete path to the bitfile used for the task session.
        :return: None
        """
        if (self.controllertype == 'fpga') or (self.controllertype == 'celesta_fpga'):
            self._controller.start_task_session(bitfile)
        else:
            pass

    def end_task_session(self):
        """ Close the session used during a task; using another bitfile than the default one for the FPGA.
        Only applicable if connected device is a FPGA.
        :return: None
        """
        if (self.controllertype == 'fpga') or (self.controllertype == 'celesta_fpga'):
            self._controller.end_task_session()
        else:
            pass

    def run_test_task_session(self, data):
        """ Exemplary method starting the execution of a session. It is necessary to call start_task_session previously
        to load the corresponding bitfile. This method allows to write the parameters to the registers of the FPGA and
        starts the execution. Create a method such as this one for each bitfile used in tasks.
        :param: data: exemplary placeholder for data that must be written to the FPGA registers for running the specific
        session.
        :return: None
        """
        if (self.controllertype == 'fpga') or (self.controllertype == 'celesta_fpga'):
            self._controller.run_test_task_session(data)
        else:
            pass

    def run_multicolor_imaging_task_session(self, z_planes, wavelength, values, num_laserlines, exposure):
        """ Start the execution of the session used in multicolor imaging, where synchronization between piezo
        movement, camera acquisition and lightsources is handled using an FPGA bitfile.
        Only applicable if connected device is a FPGA.

        :param: int z_planes: number of planes in a stack to perform
        :param: list[5] wavelength: list containing five elements (according to bitfile) containing the integer
                                    identifiers [0 - 4] for the laserlines
        :param: list[5] values: list containing five elements (according to the bitfile) containing the float
                                    intensities in per cent for the laserlines given in param wavelength
        :param: int num_laserlines: number of laserlines used in the imaging experiment
        :param: float exposure: exposure time of the camera in seconds

        :return: None
        """
        if self.controllertype == 'fpga':
            self._controller.run_multicolor_imaging_task_session(z_planes, wavelength, values, num_laserlines, exposure)
        else:
            pass

    def run_celesta_multicolor_imaging_task_session(self, z_planes, wavelength, num_laserlines, exposure):
        if self.controllertype == 'celesta_fpga':
            self._controller.run_celesta_multicolor_imaging_task_session(z_planes, wavelength, num_laserlines, exposure)
        else:
            pass

    def run_celesta_roi_multicolor_imaging_task_session(self, z_planes, wavelength, num_laserlines, exposure):
        if self.controllertype == 'celesta_fpga':
            self._controller.run_celesta_roi_multicolor_imaging_task_session(z_planes, wavelength, num_laserlines,
                                                                             exposure)
        else:
            pass

# Lumencor celesta specific methods ------------------------------------------------------------------------------------

    def lumencor_wakeup(self):
        """ Wake up the lumencor celesta source when it is in standby mode. This is needed in tasks where long
        pauses between imaging sequences might occur.

        :return: None
        """
        self._controller.wakeup()

    def lumencor_set_laser_line_intensities(self, intensity_dict):
        """ Read the intensity dictionary and translates it into a list of intensities fit for the celesta. Set the
        emission state of all lines to OFF.

        :param: dict intensity_dict
        :return: list intensity - contains the intensity of each laser line
        :return: list laser_on - contains the emission state of each laser line
        """
        intensity, laser_on = self.lumencor_read_intensity_dict(intensity_dict)
        self._controller.apply_voltage(intensity, [0] * len(intensity))

    def lumencor_set_laser_line_emission(self, laser_on):
        """ Set the emission state of all the laser lines without changing the intensity values
        """
        self._controller.set_state_all_laser_lines(laser_on)

    @staticmethod
    def lumencor_read_intensity_dict(intensity_dict):
        """ Define the intensity of each laser lines of the celesta source. Set emission states of all laser lines to 1
        if the intensity is above zero.
        """
        intensity = []
        laser_on = []
        for key in intensity_dict:
            intensity.append(intensity_dict[key] * 10)
            if intensity_dict[key] == 0:
                laser_on.append(0)
            else:
                laser_on.append(1)

        return intensity, laser_on

    def lumencor_set_ttl(self, ttl_state):
        """ Define whether the celesta source can be controlled through external ttl control.

        :param: bool ttl_state: True: source can be controlled by external trigger
        :return: None
        """
        self._controller.set_ttl(ttl_state)

# ----------------------------------------------------------------------------------------------------------------------
# Methods to handle the user interface state
# ----------------------------------------------------------------------------------------------------------------------

    def stop_laser_output(self):
        """ Allows to stop the laser output programmatically, for example in the preparation steps of a task.
        Emits a signal to reset the state of the GUI buttons / controls. """
        if self.enabled:
            self.voltage_off()
            self.sigLaserStopped.emit()

    def disable_laser_actions(self):
        """ This method provides a security to avoid all laser related actions from GUI,
        for example during Tasks. """
        self.sigDisableLaserActions.emit()
        sleep(0.5)

    def enable_laser_actions(self):
        """ This method resets all laser related actions from GUI to callable state, for example after Tasks. """
        self.sigEnableLaserActions.emit()
        sleep(0.5)