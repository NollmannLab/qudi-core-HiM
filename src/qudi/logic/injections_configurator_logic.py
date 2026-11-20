# -*- coding: utf-8 -*-

"""
# Author: F.Barho - adapted to qudi-core by JB Fiche
# Created on 2021-03-02 -> Reformated: 2026-07-31
# This module contains the logic to configure an injection sequence.

qudi-core is free software: you can redistribute it and/or modify it under the terms of the GNU General Public License
as published by the Free Software Foundation, either version 3 of the License, or (at your option) any later version.

Qudi is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU General Public License for more details.

You should have received a copy of the GNU General Public License along with Qudi. If not, see <http://www.gnu.org/licenses/>.
"""

import math
import yaml
import re
from pathlib import Path

from qtpy import QtCore
from qudi.core.module import LogicBase
from qudi.core.configoption import ConfigOption
from qudi.core.connector import Connector
from scipy.optimize import _root

# Name of the buffer entry written for the probe needle in every injections file. The tasks read the probe valve
# from the outlet of this entry (tasks/common/fluidics_steps.py).
PROBE_BUFFER_NAME = 'Probe'

# Needle rinsing after each Hi-M cycle (key needle_rinsing_time of the injections file, seconds; 0 = no rinse)
DEFAULT_NEEDLE_RINSING_TIME_S = 30
NEEDLE_RINSING_TIME_RANGE_S = (0, 600)


# ======================================================================================================================
# Time estimates of an injection sequence (pure functions, no Qt)
# ======================================================================================================================

def _step_values(step):
    """(product, volume, flowrate, time) of a step: an item of a sequence model (procedure, product, volume, flowrate,
    time) or an entry of an injections file (dict with the same keys)."""
    if isinstance(step, dict):
        return step.get('product'), step.get('volume'), step.get('flowrate'), step.get('time')
    _, product, volume, flowrate, time = step
    return product, volume, flowrate, time


def _positive_number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and value > 0


def _step_time(step):
    """Duration (s) of one step, or None when it cannot be estimated: injection step -> volume (ul) / flowrate
    (ul/min) * 60, None if the volume or the flowrate is missing or zero; incubation step (product None) -> its time,
    None if the time is missing or negative."""
    product, volume, flowrate, time = _step_values(step)
    if product is None:
        if isinstance(time, (int, float)) and not isinstance(time, bool) and time >= 0:
            return float(time)
        return None
    if _positive_number(volume) and _positive_number(flowrate):
        return volume / flowrate * 60.
    return None


def estimate_sequence_time(steps) -> float:
    """Estimated duration (s) of an injection sequence: sum of the injection steps (volume / flowrate * 60) and of
    the incubation steps (their time). Steps that cannot be estimated (missing or zero volume or flowrate, missing
    incubation time) count as 0 - see ignored_sequence_steps. Minimum time: valve switching, needle moves and the
    flow regulation ramp are not included.

    :param steps: items of a sequence model (procedure, product, volume, flowrate, time) or entries of an injections
                  file (dicts with the same keys)
    :return: float seconds
    """
    return float(sum(t for t in (_step_time(step) for step in steps) if t is not None))


def ignored_sequence_steps(steps) -> list:
    """Numbers (1-based) of the steps that estimate_sequence_time ignores (missing or zero volume or flowrate,
    missing incubation time)."""
    return [number for number, step in enumerate(steps, 1) if _step_time(step) is None]


def format_minutes(seconds) -> str:
    """Duration in minutes, one decimal, with the unit: 480 -> '8.0 min', 90 -> '1.5 min'."""
    return f'{float(seconds) / 60.:.1f} min'


def format_hours_minutes(seconds) -> str:
    """Duration rounded to the minute, in hours and minutes: 4320 -> '1 h 12 min', 600 -> '10 min' (no hours
    below one hour)."""
    total_min = int(math.floor(float(seconds) / 60. + 0.5))  # half a minute rounds up
    hours, minutes = divmod(total_min, 60)
    return f'{hours} h {minutes} min' if hours else f'{minutes} min'


def experiment_time_estimates(hybridization_steps, photobleaching_steps, needle_rinsing_time, number_of_probes) -> dict:
    """Time estimates (s) of a Hi-M experiment from its injections:
        hybridization_s, photobleaching_s: estimate_sequence_time of each list
        rinsing_s: needle rinse after each cycle
        cycle_s: hybridization_s + photobleaching_s + rinsing_s
        number_of_probes: one cycle per probe
        experiment_s: cycle_s * number_of_probes
        hybridization_ignored, photobleaching_ignored: ignored_sequence_steps of each list
    Minimum times: valve switching, needle moves, the flow regulation ramp and the imaging are not included."""
    hybridization = estimate_sequence_time(hybridization_steps)
    photobleaching = estimate_sequence_time(photobleaching_steps)
    cycle = hybridization + photobleaching + float(needle_rinsing_time)
    return {'hybridization_s': hybridization, 'photobleaching_s': photobleaching,
            'rinsing_s': float(needle_rinsing_time), 'cycle_s': cycle, 'number_of_probes': int(number_of_probes),
            'experiment_s': cycle * int(number_of_probes),
            'hybridization_ignored': ignored_sequence_steps(hybridization_steps),
            'photobleaching_ignored': ignored_sequence_steps(photobleaching_steps)}

# ======================================================================================================================
# Child classes of QAbstractListModel for the List Views
# ======================================================================================================================

class BufferListModel(QtCore.QAbstractListModel):
    """ This class contains the model class for the listview with the buffer names and the associated valve
    consisting of entries of the form (buffername, valve number)
    """

    def __init__(self, *args, items=None, **kwargs):
        super(BufferListModel, self).__init__(*args, **kwargs)
        self.items = items or []

    def data(self, index, role):
        if role == QtCore.Qt.DisplayRole:
            buffername, valve_number = self.items[index.row()]
            return f'{buffername}: Valve {valve_number}'

    def rowCount(self, index):
        return len(self.items)


class ProbePositionModel(QtCore.QAbstractListModel):
    """ This class contains the model class for the listview with the probe names and the associated positions
    consisting of entries of the form (probe name, position number)
    """

    def __init__(self, *args, items=None, **kwargs):
        super(ProbePositionModel, self).__init__(*args, **kwargs)
        self.items = items or []

    def data(self, index, role):
        if role == QtCore.Qt.DisplayRole:
            probename, position_number = self.items[index.row()]
            return f'{probename}: Position {position_number}'

    def rowCount(self, index):
        return len(self.items)


class InjectionSequenceModel(QtCore.QAbstractListModel):
    """ This class contains the model class for the listview with the injection parameters
    consisting of entries of the form (procedure, product, volume, flowrate, time)
    """
    def __init__(self, *args, items=None, **kwargs):
        super(InjectionSequenceModel, self).__init__(*args, **kwargs)
        self.items = items or []

    def data(self, index, role):
        if role == QtCore.Qt.DisplayRole:
            procedure, product, volume, flowrate, time = self.items[index.row()]
            if product is None:  # then it is an incubation step
                return f'{index.row()+1}: Incubation time: {time} s'
            else:  # injection step
                product = str.split(product, ':')[0]  # display only the name of the product and not the valve number
                return f'{index.row()+1}: {product}, {volume} ul, {flowrate} ul/min'

    def rowCount(self, index):
        return len(self.items)


# ======================================================================================================================
# Logic class
# ======================================================================================================================

class InjectionsLogic(LogicBase):
    """
    Class containing the logic to configure and save an injection sequence

    Example config for copy-paste:

    injections_logic:
        module.Class: 'injections_logic.InjectionsLogic'
        probe_valve_outlet: 7
        injections_directory: 'C:\\Users\\sCMOS-1\\qudi_files\\qudi_injection_parameters'
        number_of_valve_positions: 8
        number_of_probes: 100

    injections_directory: folder of the injections files. The GUIs that save or open injections files
    (injections GUI, experiment configurator) start their file dialogs there (read-only property
    injections_directory).

    probe_valve_outlet: outlet of the buffer valve connected to the probe needle on this setup. It is written
    into every injections file as the buffer entry PROBE_BUFFER_NAME ('Probe') -> outlet; the fluidics and Hi-M
    tasks read the probe valve from the injections files written with it (no separate task option).

    Needle rinsing time (needle_rinsing_time, s, NEEDLE_RINSING_TIME_RANGE_S, default
    DEFAULT_NEEDLE_RINSING_TIME_S): rinse of the needle after each Hi-M cycle, 0 = no rinse. Written in the
    injections file (top-level key needle_rinsing_time) and read by the Hi-M task; files without the key load with
    the default (info line). set_needle_rinsing_time refuses values outside the range; sigRinsingTimeChanged(int)
    is emitted when the value changes and by load_injections.

    Time estimates (time_estimates(), see experiment_time_estimates; computed in seconds, shown by the GUI in
    minutes with format_minutes / format_hours_minutes): hybridization and photobleaching lists, per-cycle total
    (+ needle rinse) and whole experiment (one cycle per probe). sigTimeEstimatesChanged is
    emitted whenever a list, the probes or the rinsing time change (and after load_injections).
    """
    # define connectors to logic modules
    valve = Connector(name='valve_logic', interface='FluidicsValveLogic')
    robot = Connector(name='robot_logic', interface='FluidicsRobotLogic')

    # outlet of the buffer valve connected to the probe needle on this setup (see the class docstring)
    probe_valve_number = ConfigOption('probe_valve_outlet', missing='error', converter=int)
    buffer_valve_address = ConfigOption('buffer_valve_address', missing='error')
    _injections_directory = ConfigOption('injections_directory', default='', missing='warn')

    # signals
    sigBufferListChanged = QtCore.Signal()
    sigProbeListChanged = QtCore.Signal()
    sigHybridizationListChanged = QtCore.Signal()
    sigPhotobleachingListChanged = QtCore.Signal()
    sigIncompleteLoad = QtCore.Signal()
    sigProbeNeedleModeChanged = QtCore.Signal(str)  # probe needle mode set by load_injections
    sigRinsingTimeChanged = QtCore.Signal(int)  # needle rinsing time (s): changed, or set by load_injections
    sigTimeEstimatesChanged = QtCore.Signal()  # a list, the probes or the rinsing time changed (see time_estimates)

    # attributes
    _robot = None
    _valve = None
    num_valve_positions = 0
    num_probes = 0
    procedures = ['Hybridization', 'Photobleaching']
    products = [PROBE_BUFFER_NAME]

    # needle behaviour when the probe valve is used several times in one sequence:
    # 'next' -> move to the next tube (tube + 1) for each new probe injection, 'same' -> stay in the same tube
    PROBE_NEEDLE_MODES = ('next', 'same')
    DEFAULT_PROBE_NEEDLE_MODE = 'next'
    _probe_needle_mode = DEFAULT_PROBE_NEEDLE_MODE
    # needle rinsing time (module constants, also read by the GUI)
    NEEDLE_RINSING_TIME_RANGE_S = NEEDLE_RINSING_TIME_RANGE_S
    DEFAULT_NEEDLE_RINSING_TIME_S = DEFAULT_NEEDLE_RINSING_TIME_S
    _needle_rinsing_time = DEFAULT_NEEDLE_RINSING_TIME_S

    buffer_dict = {}  # key: value = valve_number: buffer_name (to make sure that each valve is only used once)
    probe_dict = {}  # key: value = position_number: probe_name (same comment)

    def on_activate(self):
        """ Initialisation performed during activation of the module.
        """

        # instantiate logic connections
        self._robot = self.robot()
        self._valve = self.valve()

        # load the number of outlets from the valve logic
        self.num_valve_positions = self._valve.valve_dict[self.buffer_valve_address]['number_outputs']

        # load the number of available position for the pipetting robot
        self.num_probes = self._robot.max_num_probes

        self.buffer_list_model = BufferListModel()
        self.probe_position_model = ProbePositionModel()
        self.hybridization_injection_sequence_model = InjectionSequenceModel()
        self.photobleaching_injection_sequence_model = InjectionSequenceModel()

        # time estimates follow every change of the lists, the probes and the rinsing time
        for signal in (self.sigHybridizationListChanged, self.sigPhotobleachingListChanged, self.sigProbeListChanged,
                       self.sigRinsingTimeChanged):
            signal.connect(self._emit_time_estimates)
        self._needle_rinsing_time = DEFAULT_NEEDLE_RINSING_TIME_S

        # add the probe entry as default into the bufferlist
        self.add_buffer(PROBE_BUFFER_NAME, self.probe_valve_number)

        self._probe_needle_mode = self.DEFAULT_PROBE_NEEDLE_MODE

    def on_deactivate(self):
        """ Perform required deactivation. """
        for signal in (self.sigHybridizationListChanged, self.sigPhotobleachingListChanged, self.sigProbeListChanged,
                       self.sigRinsingTimeChanged):
            try:
                signal.disconnect(self._emit_time_estimates)
            except (RuntimeError, TypeError):
                pass

# ----------------------------------------------------------------------------------------------------------------------
# Needle rinsing time and time estimates
# ----------------------------------------------------------------------------------------------------------------------

    @property
    def needle_rinsing_time(self) -> int:
        """ Needle rinsing after each Hi-M cycle (s, 0 = no rinse), written in the injections file. """
        return self._needle_rinsing_time

    @needle_rinsing_time.setter
    def needle_rinsing_time(self, value):
        self.set_needle_rinsing_time(value)

    @staticmethod
    def _valid_rinsing_time(value) -> bool:
        low, high = NEEDLE_RINSING_TIME_RANGE_S
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return False
        return low <= value <= high and float(value).is_integer()  # NaN and inf fail the range test

    @QtCore.Slot(int)
    def set_needle_rinsing_time(self, value):
        """ Set the needle rinsing time.
        :param: int value: seconds, within NEEDLE_RINSING_TIME_RANGE_S (0 = no rinse)
        :return: bool: True if the value was set, False if it is not valid (error logged, value unchanged)
        """
        if not self._valid_rinsing_time(value):
            low, high = NEEDLE_RINSING_TIME_RANGE_S
            self.log.error(f'Invalid needle rinsing time {value!r} - a whole number of seconds within {low}..{high} '
                           f'is expected.')
            return False
        value = int(value)
        if value != self._needle_rinsing_time:
            self._needle_rinsing_time = value
            self.sigRinsingTimeChanged.emit(value)
        return True

    def time_estimates(self) -> dict:
        """ Time estimates (s) of the current injections: see experiment_time_estimates (hybridization_s,
        photobleaching_s, rinsing_s, cycle_s, number_of_probes, experiment_s, hybridization_ignored,
        photobleaching_ignored). """
        return experiment_time_estimates(self.hybridization_injection_sequence_model.items,
                                         self.photobleaching_injection_sequence_model.items,
                                         self._needle_rinsing_time, len(self.probe_dict))

    def _emit_time_estimates(self, *args):
        self.sigTimeEstimatesChanged.emit()

# ----------------------------------------------------------------------------------------------------------------------
# Probe needle mode
# ----------------------------------------------------------------------------------------------------------------------

    @property
    def injections_directory(self) -> str:
        """Folder of the injections files (config option injections_directory, '' if not set)."""
        return str(self._injections_directory or '')

    @property
    def probe_needle_mode(self):
        """ Needle behaviour when the probe valve is used several times in the sequence: 'next' (move to the next
        tube for each new probe injection) or 'same' (stay in the same tube). """
        return self._probe_needle_mode

    @probe_needle_mode.setter
    def probe_needle_mode(self, mode):
        self.set_probe_needle_mode(mode)

    @QtCore.Slot(str)
    def set_probe_needle_mode(self, mode):
        """ Set the probe needle mode.
        :param: str mode: 'next' or 'same'
        :return: bool: True if the mode was set, False if the value is not valid (error logged, mode unchanged)
        """
        if mode not in self.PROBE_NEEDLE_MODES:
            self.log.error(f'Invalid probe needle mode {mode!r} - valid values: {list(self.PROBE_NEEDLE_MODES)}.')
            return False
        self._probe_needle_mode = mode
        return True

# ----------------------------------------------------------------------------------------------------------------------
# Methods to insert / delete items into the listview models
# ----------------------------------------------------------------------------------------------------------------------

    def add_buffer(self, buffername, valve_number):
        """ This method adds an entry to the buffer dict and to the buffer list model and informs the GUI that the
        data was changed.
        :param: str buffername
        :param: int valve_number
        """
        self.buffer_dict[valve_number] = buffername
        # synchronize buffer_dict and list_model, this approach also ensures that each valve number is only set once
        self.buffer_list_model.items = [(self.buffer_dict[key], key) for key in sorted(self.buffer_dict.keys())]
        self.sigBufferListChanged.emit()

    def delete_buffer(self, index):
        """ This method deletes a single entry from the buffer list model and from the buffer dict. The signal
        informs the GUI that the data was changed.
        :param: QtCore.QModelIndex index
        """
        key = self.buffer_list_model.items[index.row()][1]  # the valve number
        if key == self.probe_valve_number:
            pass
        else:
            del self.buffer_dict[key]
            del self.buffer_list_model.items[index.row()]
            self.sigBufferListChanged.emit()

    def delete_all_buffer(self):
        """ This method resets the buffer dict and deletes all items from the buffer list model. The GUI is informed
        that the data has changed.
        """
        self.buffer_dict = {}
        self.buffer_list_model.items = []
        # add the default entry Probe
        self.add_buffer(PROBE_BUFFER_NAME, self.probe_valve_number)
        self.sigBufferListChanged.emit()

    def add_probe(self, probename, probe_position):
        """ This method adds an entry to the probe dict and to the probe position model and informs the GUI that the
        data was changed.
        :param: str probename
        :param: int probe_position
        """
        self.probe_dict[probe_position] = probename
        # synchronize buffer_dict and list_model, this approach also ensures that each valve number is only set once
        self.probe_position_model.items = [(self.probe_dict[key], key) for key in sorted(self.probe_dict.keys())]
        self.sigProbeListChanged.emit()

    def delete_probe(self, index):
        """ This method deletes a single entry from the probe position model and from the probe dict. The signal
        informs the GUI that the data was changed.
        :param: QtCore.QModelIndex index
        """
        key = self.probe_position_model.items[index.row()][1]   # the probe position number
        # delete the entry both in the dictionary and in the list model
        del self.probe_dict[key]
        del self.probe_position_model.items[index.row()]
        self.sigProbeListChanged.emit()

    def delete_all_probes(self):
        """ This method resets the probe position dict and deletes all items from the probe position model. The GUI is
        informed that the data has changed.
        """
        self.probe_dict = {}
        self.probe_position_model.items = []
        self.sigProbeListChanged.emit()

    @QtCore.Slot(str, str, int, int)
    def add_injection_step(self, procedure, product, volume, flowrate):
        """ This method adds an entry tho the hybridization or photobleaching sequence model and informs the
        GUI that the underlying data has changed.
        :param: str procedure: identifier to select to which model the entry should be added
        :param: str product
        :param: int volume: amount of product to be injected (in ul)
        :param: int flowrate: target flowrate in ul/min
        """
        if procedure == 'Hybridization':
            self.hybridization_injection_sequence_model.items.append((procedure, product, volume, flowrate, None))
            self.sigHybridizationListChanged.emit()
        elif procedure == 'Photobleaching':
            self.photobleaching_injection_sequence_model.items.append((procedure, product, volume, flowrate, None))
            self.sigPhotobleachingListChanged.emit()
        else:
            pass

    @QtCore.Slot(str, int)
    def add_incubation_step(self, procedure, time):
        """ This method adds an incubation time entry tho the hybridization or photobleaching sequence model and emits
        a signal to inform the GUI that the underlying data has changed.
        :param: str procedure: identifier to select to which model the entry should be added
        :param: int time: incubation time in seconds
        """
        if procedure == 'Hybridization':
            self.hybridization_injection_sequence_model.items.append((procedure, None, None, None, time))
            self.sigHybridizationListChanged.emit()
        elif procedure == 'Photobleaching':
            self.photobleaching_injection_sequence_model.items.append((procedure, None, None, None, time))
            self.sigPhotobleachingListChanged.emit()
        else:
            pass

    @QtCore.Slot(QtCore.QModelIndex)
    def delete_hybr_step(self, index):
        """ This method deletes an entry from the hybridization sequence model and notifies about data modification.
        @:param: QtCore.QModelIndex index: selected entry
        """
        del self.hybridization_injection_sequence_model.items[index.row()]
        self.sigHybridizationListChanged.emit()

    @QtCore.Slot(QtCore.QModelIndex)
    def delete_photobl_step(self, index):
        """ This method deletes an entry from the photobleaching sequence model and notifies about data modification.
        @:param: QtCore.QModelIndex index: selected entry
        """
        del self.photobleaching_injection_sequence_model.items[index.row()]
        self.sigPhotobleachingListChanged.emit()

    def delete_hybr_all(self):
        """ This method deletes all entries from the hybridization sequence model and notifies about data modification.
        """
        self.hybridization_injection_sequence_model.items = []
        self.sigHybridizationListChanged.emit()

    def delete_photobl_all(self):
        """ This method deletes all entries from the photobleaching sequence model and notifies about data modification.
        """
        self.photobleaching_injection_sequence_model.items = []
        self.sigPhotobleachingListChanged.emit()

# ----------------------------------------------------------------------------------------------------------------------
# Methods to load and save files
# ----------------------------------------------------------------------------------------------------------------------

    def load_injections(self, path):
        """ This method allows to open a file and fills in data to the buffer dict, probe dict and to the models
        if the specified document contains all relevant information. The GUI is notified and updated with the new data.
        :param: str path: full path to the file
        """
        try:
            # delete the current content of models
            self.delete_all_buffer()
            self.delete_all_probes()
            self.delete_hybr_all()
            self.delete_photobl_all()

            with open(path, 'r') as stream:
                documents = yaml.safe_load(stream)  # yaml.full_load(stream)  # use this when pyyaml updated everywhere
                self.buffer_dict = documents['buffer']
                self.probe_dict = documents['probes']
                hybridization_list = documents['hybridization list']
                photobleaching_list = documents['photobleaching list']
                # files written before this key existed use the default mode
                probe_needle_mode = documents.get('probe_needle_mode', self.DEFAULT_PROBE_NEEDLE_MODE)
                # files written before this key existed use the default needle rinsing time
                if 'needle_rinsing_time' in documents:
                    rinsing_time = documents['needle_rinsing_time']
                else:
                    rinsing_time = DEFAULT_NEEDLE_RINSING_TIME_S
                    self.log.info(f'{path}: no needle_rinsing_time - default needle rinsing time '
                                  f'{DEFAULT_NEEDLE_RINSING_TIME_S} s used.')

                # update the models based on the dictionaries / lists content
                self.buffer_list_model.items = [(self.buffer_dict[key], key) for key in self.buffer_dict]
                self.probe_position_model.items = [(self.probe_dict[key], key) for key in self.probe_dict]

                for i in range(len(hybridization_list)):
                    entry = hybridization_list[i]  # entry is a dict
                    self.hybridization_injection_sequence_model.items.append((entry['procedure'], entry['product'], entry['volume'], entry['flowrate'], entry['time']))

                for i in range(len(photobleaching_list)):
                    entry = photobleaching_list[i]  # entry is a dict
                    self.photobleaching_injection_sequence_model.items.append((entry['procedure'], entry['product'], entry['volume'], entry['flowrate'], entry['time']))

                self.sigBufferListChanged.emit()
                self.sigProbeListChanged.emit()
                self.sigHybridizationListChanged.emit()
                self.sigPhotobleachingListChanged.emit()

                if probe_needle_mode not in self.PROBE_NEEDLE_MODES:
                    self.log.error(f'Invalid probe needle mode {probe_needle_mode!r} in {path} (valid values: '
                                   f'{list(self.PROBE_NEEDLE_MODES)}) - using {self.DEFAULT_PROBE_NEEDLE_MODE!r}.')
                    probe_needle_mode = self.DEFAULT_PROBE_NEEDLE_MODE
                self._probe_needle_mode = probe_needle_mode
                self.sigProbeNeedleModeChanged.emit(self._probe_needle_mode)

                if not self._valid_rinsing_time(rinsing_time):
                    low, high = NEEDLE_RINSING_TIME_RANGE_S
                    self.log.error(f'Invalid needle_rinsing_time {rinsing_time!r} in {path} (whole number of seconds '
                                   f'within {low}..{high}) - using {DEFAULT_NEEDLE_RINSING_TIME_S} s.')
                    rinsing_time = DEFAULT_NEEDLE_RINSING_TIME_S
                self._needle_rinsing_time = int(rinsing_time)
                self.sigRinsingTimeChanged.emit(self._needle_rinsing_time)
                self.sigTimeEstimatesChanged.emit()

        except KeyError:
            self.log.warning('Injections not loaded. Document is incomplete.')
            self.sigIncompleteLoad.emit()

    def save_injections(self, path):
        """ This method allows to write the data from the models and from the buffer dict and probe position dict
        to a file. For readability, hybridization and photobleaching sequence model entries are converted into a
        dictionary format.
        @param: str path: full path
        """
        file_path = Path(path)
        if file_path.suffix.lower() != ".yaml":
            file_path = file_path.with_suffix(".yaml")

        # check consistency in injection sequences
        if self.check_injection_sequence_consistency():

            # prepare the list entries in dictionary format for good readability in the file
            hybridization_list = []
            photobleaching_list = []

            for entry_num, item in enumerate(self.hybridization_injection_sequence_model.items, 1):
                if item[1] is not None:
                    product = str.split(item[1], ':')[0]  # write just the product name, not the corresponding valve pos
                else:
                    product = None
                entry = self.make_dict_entry(entry_num, item[0], product, item[2], item[3], item[4])
                hybridization_list.append(entry)

            for entry_num, item in enumerate(self.photobleaching_injection_sequence_model.items, 1):
                if item[1] is not None:
                    product = str.split(item[1], ':')[0]
                else:
                    product = None
                entry = self.make_dict_entry(entry_num, item[0], product, item[2], item[3], item[4])
                photobleaching_list.append(entry)

            with open(file_path, 'w') as file:
                dict_file = {'buffer': self.buffer_dict, 'probes': self.probe_dict, 'hybridization list': hybridization_list, 'photobleaching list': photobleaching_list,
                             'probe_needle_mode': self._probe_needle_mode,
                             'needle_rinsing_time': self._needle_rinsing_time}
                yaml.safe_dump(dict_file, file, default_flow_style=False)  # , sort_keys=False
                self.log.info('Injections saved to {}'.format(file_path))

    def check_injection_sequence_consistency(self):
        """ check whether the injection method is consistent (the buffers indicated in the injections sequences should
        match all the buffers saved in the buffer dictionary). Also, check at least one probe is indicated.

        @return: bool - False if an error was found in the injections sequence.
        """
        save_parameters = True
        # check consistency between buffers list and injection procedures
        if not self.probe_dict:
            self.log.error('The injections parameters cannot be saved. At least one probe is required.')
            save_parameters = False

        # convert the buffer dictionary into a list
        buffer_list = []
        for value in self.buffer_dict.values():
            buffer_list.append(value)

        # test if all the buffers indicated in the hybridization sequence are valid
        colon_r = re.compile('\w+:')
        for step in self.hybridization_injection_sequence_model.items:
            injection_buffer = step[1]
            # if this step is an incubation, skip it
            if injection_buffer is None:
                continue
            # when creating from scratch the sequence, all buffers are saved as 'buffer : valve'. However, when loading
            # a sequence from a file, the position of the valve is not indicated anymore. To avoid error, we search
            # first for the presence of ":" and if it is found, we keep only the name of the buffer.
            find_colon = colon_r.findall(injection_buffer)
            if find_colon:
                injection_buffer = find_colon[0]
            # check if the injection_buffer is in the buffer dictionary
            r = re.compile(injection_buffer + '*')
            if not list(filter(r.match, buffer_list)):
                self.log.error(f'There is an error in the hybridization sequence. \
                                        {injection_buffer} is not defined in the buffer list')
                save_parameters = False
                break

        # test if all the buffers indicated in the photobleaching sequence are valid
        for step in self.photobleaching_injection_sequence_model.items:
            injection_buffer = step[1]
            # if this step is an incubation, skip it
            if injection_buffer is None:
                continue
            # when creating from scratch the sequence, all buffers are saved as 'buffer : valve'. However, when loading
            # a sequence from a file, the position of the valve is not indicated anymore. To avoid error, we search
            # first for the presence of ":" and if it is found, we keep only the name of the buffer.
            find_colon = colon_r.findall(injection_buffer)
            if find_colon:
                injection_buffer = find_colon[0]
            # check if the injection_buffer is in the buffer dictionary
            r = re.compile(injection_buffer + '*')
            if not list(filter(r.match, buffer_list)):
                self.log.error(f'There is an error in the photobleaching sequence. \
                                        {injection_buffer} is not defined in the buffer list')
                save_parameters = False
                break

        return save_parameters

    @staticmethod
    def make_dict_entry(step_num, procedure, product, volume, flowrate, time=None):
        """ Helper function.
        :param int step_num: number of the current step in an injection list
        :param str procedure: name of the procedure: Hybridization or Photobleaching
        :param str product: name of the product
        :param int volume: quantity of product in ul to be injected
        :param int flowrate: target flowrate in ul/min
        :param int time: time in seconds for incubation steps
        """
        inj_step_dict = {'step_number': step_num, 'procedure': procedure, 'product': product, 'volume': volume,
                         'flowrate': flowrate, 'time': time}
        return inj_step_dict
