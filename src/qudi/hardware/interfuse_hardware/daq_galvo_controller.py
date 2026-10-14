# -*- coding: utf-8 -*-
"""
Author: JB Fiche - written for qudi-core-HiM with Claude code
Created: 2026-10-12

Qudi-core-HiM hardware module for a galvo mirror driven by one analog output of a DAQ.

Used on the OPM microscope, where the beam-sweep galvo is driven by AO1 of the NI DAQ. The module
only maps the GalvoInterface onto one named DAQ analog-output task (write_named_ao); any DAQ backend
implementing DaqInterface can be used (NI, MCC, dummy).

-----------------------------------------------------------------------------------
qudi-core is free software: you can redistribute it and/or modify it under the terms of the GNU General Public License
as published by the Free Software Foundation, either version 3 of the License, or (at your option) any later version.

Qudi is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU General Public License for more details.

You should have received a copy of the GNU General Public License along with Qudi. If not, see <http://www.gnu.org/licenses/>.
-----------------------------------------------------------------------------------

Modified with Claude code (Anthropic)
"""

from typing import Optional, Tuple

from qudi.core.configoption import ConfigOption
from qudi.core.connector import Connector
from qudi.interface.daq_interface import DaqInterface
from qudi.interface.galvo_interface import GalvoInterface
from qudi.util.mutex import Mutex


class DaqGalvoController(GalvoInterface):
    """Galvo mirror positioned by the voltage of one DAQ analog-output task.

    Activation checks min_voltage < max_voltage and min_voltage <= rest_voltage <= max_voltage, and
    that [min_voltage, max_voltage] fits inside the DAQ task's own voltage range; any inconsistency
    stops the activation with an error naming the option (raised, so qudi logs it and keeps the
    module deactivated). The galvo is then moved to rest_voltage.

    At run time, set_voltage() / go_to_rest() return True on success. A voltage outside
    [min_voltage, max_voltage] or a failed DAQ write is logged as an error and returns False;
    nothing is written and the stored voltage is unchanged.

    Config example for copy-paste (hardware:):

        galvo:
            module.Class: 'interfuse_hardware.daq_galvo_controller.DaqGalvoController'
            connect:
                daq: 'nidaq_6738'
            options:
                output_task: 'galvo'    # name of the DAQ analog-output task (ao_channels)
                min_voltage: -5.0       # V
                max_voltage: 5.0        # V
                rest_voltage: 0.0       # V, used on activation, deactivation and go_to_rest()
    """

    daq = Connector(name='daq', interface='DaqInterface')

    _output_task = ConfigOption('output_task', missing='error', converter=str)
    _min_voltage = ConfigOption('min_voltage', default=-5.0, converter=float)
    _max_voltage = ConfigOption('max_voltage', default=5.0, converter=float)
    _rest_voltage = ConfigOption('rest_voltage', default=0.0, converter=float)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._lock = Mutex()  # write + stored value: called from task threads and the GUI thread
        self._daq: Optional[DaqInterface] = None
        self._voltage: float = 0.0

    def on_activate(self) -> None:
        """Connect to the DAQ, check the configured voltages and move the galvo to rest.

        A configuration error raises: qudi logs it and leaves the module deactivated, which is
        safer than running with an unusable galvo.
        """
        self._daq = self.daq()
        self._check_configuration()
        if not self.go_to_rest():
            raise RuntimeError(f'Galvo "{self.module_name}": could not move to the rest voltage '
                               f'({self._rest_voltage} V) at activation - see the error above.')

    def on_deactivate(self) -> None:
        """Move the galvo to rest (errors are logged, never raised), then release the DAQ."""
        self.go_to_rest()
        self._daq = None

    def _check_configuration(self) -> None:
        """Raise ValueError with a clear message if the configured voltages are inconsistent."""
        vmin, vmax, vrest = self._min_voltage, self._max_voltage, self._rest_voltage
        if not vmin < vmax:
            raise ValueError(f'Galvo "{self.module_name}": min_voltage ({vmin} V) must be smaller '
                             f'than max_voltage ({vmax} V).')
        if not vmin <= vrest <= vmax:
            raise ValueError(f'Galvo "{self.module_name}": rest_voltage ({vrest} V) must be within '
                             f'[min_voltage, max_voltage] = [{vmin}, {vmax}] V.')
        try:
            task_range = self._daq.get_task_range(self._output_task)
        except KeyError as err:
            raise ValueError(f'Galvo "{self.module_name}": output_task "{self._output_task}" is '
                             f'not an analog-output task of the connected DAQ ({err}).') from err
        if task_range is not None:
            task_min, task_max = (float(v) for v in task_range)
            if vmin < task_min or vmax > task_max:
                raise ValueError(f'Galvo "{self.module_name}": [min_voltage, max_voltage] = '
                                 f'[{vmin}, {vmax}] V does not fit inside the voltage range '
                                 f'[{task_min}, {task_max}] V of DAQ task "{self._output_task}".')

    # GalvoInterface ------------------------------------------------------------------------------
    def set_voltage(self, voltage: float) -> bool:
        """Write the galvo control voltage (V). Returns True if written.

        Out of [min_voltage, max_voltage], not a number, or a failed DAQ write: log an error,
        write nothing (stored voltage unchanged) and return False.
        """
        try:
            voltage = float(voltage)
        except (TypeError, ValueError):
            self.log.error(f'Galvo voltage {voltage!r} refused: not a number. Nothing was written.')
            return False
        if not self._min_voltage <= voltage <= self._max_voltage:
            self.log.error(f'Galvo voltage {voltage} V refused: outside the allowed range '
                           f'[{self._min_voltage}, {self._max_voltage}] V. Nothing was written.')
            return False
        with self._lock:
            if self._daq is None:
                self.log.error('Galvo voltage not written: the galvo module is not active.')
                return False
            try:
                self._daq.write_named_ao(self._output_task, voltage)
            except Exception as err:
                self.log.error(f'Galvo voltage {voltage} V could not be written to DAQ task '
                               f'"{self._output_task}": {err}')
                return False
            self._voltage = voltage
            return True

    def get_voltage(self) -> float:
        """Return the last voltage written (V)."""
        with self._lock:
            return self._voltage

    def get_limits(self) -> Tuple[float, float]:
        """Return (min_voltage, max_voltage) in V."""
        return self._min_voltage, self._max_voltage

    def get_rest_voltage(self) -> float:
        """Return the rest voltage in V."""
        return self._rest_voltage

    def go_to_rest(self) -> bool:
        """Move the galvo to the rest voltage. Returns True on success, False otherwise."""
        return self.set_voltage(self._rest_voltage)
