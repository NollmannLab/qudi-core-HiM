# -*- coding: utf-8 -*-
"""
Qudi-CBS

This module contains the logic to control the positioning system for the probes.
An extension to Qudi.

@author: F. Barho - adapted for qudi-core-HiM by JB Fiche
Created on 2021-03-04 -> translated into qudi-core-HiM the 2026-07-21

qudi-core is free software: you can redistribute it and/or modify it under the terms of the GNU General Public License
as published by the Free Software Foundation, either version 3 of the License, or (at your option) any later version.

Qudi is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU General Public License for more details.

You should have received a copy of the GNU General Public License along with Qudi. If not, see <http://www.gnu.org/licenses/>.
-----------------------------------------------------------------------------------
"""
from time import sleep
from qtpy import QtCore
from qudi.core.module import LogicBase
from qudi.core.configoption import ConfigOption
from qudi.core.connector import Connector


# ======================================================================================================================
# Worker classes
# ======================================================================================================================

class WorkerSignals(QtCore.QObject):
    """Define the signals available from the movement polling workers.

    The movement identifier is emitted with every signal so that callbacks
    belonging to an aborted or superseded movement can be ignored safely.
    """

    sigSafetyStepFinished = QtCore.Signal(dict, dict, int)
    sigxyStepFinished = QtCore.Signal(dict, dict, int)
    sigzStepFinished = QtCore.Signal(dict, int)


class safetyMoveWorker(QtCore.QRunnable):
    """Worker thread used to delay polling of the z safety movement.

    The worker only handles the waiting time. Hardware access remains in the
    logic module thread when the emitted signal invokes the connected slot.

    :param dict pos_dict_xy: Target positions of the first and second axes.
    :param dict pos_dict_z: Final target position of the third axis.
    :param int movement_id: Identifier of the active movement sequence.
    :param float poll_interval: Waiting time before the next status query, in seconds.
    """

    def __init__(self, pos_dict_xy, pos_dict_z, movement_id, poll_interval):
        super().__init__()
        self.signals = WorkerSignals()
        self.pos_dict_xy = pos_dict_xy
        self.pos_dict_z = pos_dict_z
        self.movement_id = movement_id
        self.poll_interval = poll_interval

    @QtCore.Slot()
    def run(self):
        """Wait for one polling interval and request a safety-status update."""
        sleep(self.poll_interval)
        self.signals.sigSafetyStepFinished.emit(
            self.pos_dict_xy, self.pos_dict_z, self.movement_id
        )


class xyMoveWorker(QtCore.QRunnable):
    """Worker thread used to delay polling of an in-plane stage movement.

    The worker handles only the waiting time and emits a signal that triggers
    the position and status update in the logic module thread.

    :param dict pos_dict_xy: Target positions of the first and second axes.
    :param dict pos_dict_z: Final target position of the third axis.
    :param int movement_id: Identifier of the active movement sequence.
    :param float poll_interval: Waiting time before the next status query, in seconds.
    """

    def __init__(self, pos_dict_xy, pos_dict_z, movement_id, poll_interval):
        super().__init__()
        self.signals = WorkerSignals()
        self.pos_dict_xy = pos_dict_xy
        self.pos_dict_z = pos_dict_z
        self.movement_id = movement_id
        self.poll_interval = poll_interval

    @QtCore.Slot()
    def run(self):
        """Wait for one polling interval and request an in-plane status update."""
        sleep(self.poll_interval)
        self.signals.sigxyStepFinished.emit(
            self.pos_dict_xy, self.pos_dict_z, self.movement_id
        )


class zMoveWorker(QtCore.QRunnable):
    """Worker thread used to delay polling of the final z movement.

    The worker handles only the waiting time and emits a signal that triggers
    the position and status update in the logic module thread.

    :param dict pos_dict_z: Target position of the third axis.
    :param int movement_id: Identifier of the active movement sequence.
    :param float poll_interval: Waiting time before the next status query, in seconds.
    """

    def __init__(self, pos_dict_z, movement_id, poll_interval):
        super().__init__()
        self.signals = WorkerSignals()
        self.pos_dict_z = pos_dict_z
        self.movement_id = movement_id
        self.poll_interval = poll_interval

    @QtCore.Slot()
    def run(self):
        """Wait for one polling interval and request a z-status update."""
        sleep(self.poll_interval)
        self.signals.sigzStepFinished.emit(self.pos_dict_z, self.movement_id)


# ======================================================================================================================
# Logic class
# ======================================================================================================================

class FluidicsRobotLogic(LogicBase):
    """Class containing the logic to control the three-axis positioning system for the probes.

    The connected module can be either ``PIPipettingRobot`` or ``DummyPipettingRobot`` because both expose
    the same positioning API.

    Example configuration::

    pipetting_robot_logic:
        module.Class: 'fluidics_robot_logic.FluidicsRobotLogic'
        connect:
            robot: 'dummy_pipetting_robot'
        options:
            movement_poll_interval: 0.5  # is s - to probe the stage position
    """
    # declare connectors
    robot = Connector(interface='PipettingRobotInterface', name='robot')

    # config options
    poll_interval = ConfigOption('movement_poll_interval', 0.5, missing='warn')

    # signals
    sigUpdatePosition = QtCore.Signal(tuple)  # send during movement to update coordinates on the GUI
    sigStageMoved = QtCore.Signal(tuple)  # this signal is sent if movement was started using coordinates of stage. tuple contains the new stage position (x, y, z)
    sigStageMovedToTarget = QtCore.Signal(tuple, int)  # this signal is sent if movement was started using target position (number of probe). tuple contains the new stage position (x, y, z), int is the target position
    sigOriginDefined = QtCore.Signal()
    sigStageStopped = QtCore.Signal(tuple)  # tuple contains the current stage position (x, y, z)
    sigDisablePositioningActions = QtCore.Signal()
    sigEnablePositioningActions = QtCore.Signal()

    # attributes for the robot
    _robot = None
    grid = None
    first_axis_label = None
    second_axis_label = None
    third_axis_label = None
    z_safety_pos = 0
    max_num_probes = 0
    target_position = 0  # overwritten when movement is started using the start_move_to_target method  (target is the probe number)

    # attributes for actions
    threadpool = None
    move_stage = False  # flag
    go_to_target = False  # flag
    moving = False
    origin = None
    _movement_id = 0

    _probe_grid_dict = {}  # mapping of the probe numbers to their coordinates on the grid  {1: (0, 0), ...}
    _probe_xy_position_dict = {}  # mapping of the physical x-y or r-phi positions of the probes {(12.0, 10.0): 1, ..}}

    def on_activate(self):
        """Initialize the connector, movement state, worker pool, and probe grid.

         The configured axis labels are checked against the constraints returned
         by the connected hardware. A third axis is required because all stage
         movements use a z safety position before moving in-plane.
         """
        # connector
        self._robot = self.robot()

        # Initialize the threadpool to handle workers
        self.threadpool = QtCore.QThreadPool(self)

        # calculate the probe grid coordinates - the grid is independent of the origin that is not yet set
        self._get_grid_properties()
        self._probe_grid_dict = self.map_probe_number_to_grid_coordinates()

    def on_deactivate(self):
        """Stop movement polling and invalidate outstanding worker callbacks."""
        self.moving = False
        self._movement_id += 1
        self.move_stage = False
        self.go_to_target = False
        if hasattr(self, 'threadpool'):
            self.threadpool.clear()
            self.threadpool.waitForDone(1000)

    @property
    def _axis_labels(self):
        """Return the configured axis labels in first, second, third order.

        :return: Tuple containing the three labels used by the hardware API.
        """
        return self.first_axis_label, self.second_axis_label, self.third_axis_label

    def get_hardware_constraints(self):
        """Retrieve constraints from the connected stage.
        This is used to update the indicators on the GUI according to the connected PI or dummy stage.

        :return: (dict) Constraints indexed by the configured hardware axis labels.
        """
        return self._robot.get_constraints()

    def _get_grid_properties(self):
        """Retrieve grid properties from the connected stage."""
        grid_properties = self._robot.get_grid_properties()
        self.grid = grid_properties['grid']
        self.first_axis_label = grid_properties['axis_1']
        self.second_axis_label = grid_properties['axis_2']
        self.third_axis_label = grid_properties['axis_3']
        self.z_safety_pos = grid_properties['z_safety_pos']
        self. max_num_probes = grid_properties['max_number_tubes']

    def get_robot_parameters(self):
        """Return pipetting-robot configuration parameters.This function is called from the gui."""
        return self._robot.get_robot_parameters()

# ----------------------------------------------------------------------------------------------------------------------
# Methods defining the origin, the grid and the x-y or r-phi coordinates
# ----------------------------------------------------------------------------------------------------------------------

    def set_origin(self, origin):
        """Define the coordinates of probe position 1.

        The origin must contain one coordinate for each configured stage axis. A signal is emitted after
        the in-plane probe lookup table is generated.

        :param origin: Three-element iterable containing first-axis,
            second-axis, and third-axis positions.
        """
        if len(origin) != 3:
            raise ValueError('The positioning origin must contain exactly three coordinates.')
        self.origin = tuple(origin)

        # create a dictionary that allows to access the position number of the probe by its metric coordinates
        self._probe_xy_position_dict = self.map_xy_position_to_probe_number()
        self.sigOriginDefined.emit()

    def map_probe_number_to_grid_coordinates(self):
        """ Generate a mapping of the probes based on the coordinate system used for the grid.

        :return dict coord_dict: dictionary mapping the probe position to the corresponding grid position
        """
        return self._robot.map_probe_number_to_grid_coordinates()

    def map_xy_position_to_probe_number(self):
        """ This method calculates the in-plane coordinates given the metrics of the respective setup
        (spacing of probe positions in x, y directions or r, phi directions) and stores them in a dictionary.

        :return dict inv_dict: dictionary containing a tuple of in-plane coordinates as key and associated probe number as value.

        This dictionary serves as look-up-table in the fluidics gui module to check if the stage is currently at a probe position.
        """
        return self._robot.map_xy_position_to_probe_number(self._probe_grid_dict, self.origin)

    def get_coordinates(self, target):
        """ This method returns the (x, y) grid coordinates associated to the target position

        :param: int target: target position of the probe
        :return: int tuple (x, y)
        """
        return self._probe_grid_dict[target]

# ----------------------------------------------------------------------------------------------------------------------
# Methods to perform movements either given the target stage coordinates or the target position of the probe
# ----------------------------------------------------------------------------------------------------------------------

    def start_move_stage(self, position):
        """ This method allows to perform a movement of the 3 axis stage to the specified stage position.
        A movement to the z safety position is performed first, before doing the xy positioning.
        xy positioning is started from this method, then a loop is entered to make a call to the abort movement method
        possible.
        Finally, the z movement is done using again a loop.

        :param: float tuple position: (x, y, z) position
        """
        try:
            valid_length = len(position) == 3
        except TypeError:
            valid_length = False

        if not valid_length:
            self.log.warning('Stage position to set must be iterable of length 3. No movement done.')
            return

        if self.moving:
            self.log.warning('The stage is already moving. No new movement was started.')
            return

        # do not allow descending z below safety position when operating by move stage
        # (x y z coordinates given instead of target position)
        if position[2] > self.z_safety_pos:
            self.log.warning('z movement will not be made. z out of allowed range.')

            # redefine position using the z safety position instead of the user defined z position
            x = position[0]
            y = position[1]
            z = self.z_safety_pos
            position = (x, y, z)

        axis_label = self._axis_labels
        pos_dict = dict(zip(axis_label, position))

        # separate movement into xy and z movements for safety
        pos_dict_xy = {
            self.first_axis_label: pos_dict[self.first_axis_label],
            self.second_axis_label: pos_dict[self.second_axis_label],
        }
        pos_dict_z = {self.third_axis_label: pos_dict[self.third_axis_label]}

        self.move_stage = True  # movement initiated by start_move_stage
        self.go_to_target = False
        self._start_safety_sequence(pos_dict_xy, pos_dict_z)

        # self._robot.move_abs({'z': self.z_safety_pos})  # move to z safety position before making the xy movement
        # ready = self._robot.get_status('z')['z']
        # while not ready:
        #     sleep(0.5)
        #     ready = self._robot.get_status('z')['z']
        #
        # # start the xy movement of the translation stage
        # self._robot.move_abs(pos_dict_xy)
        #
        # # start a worker thread to monitor the xy movement
        # worker = xyMoveWorker(pos_dict_xy, pos_dict_z)
        # worker.signals.sigxyStepFinished.connect(self.move_xy_stage_loop)
        # self.threadpool.start(worker)

    def start_move_to_target(self, target_position):
        """ This method allows to perform a movement of the 3 axis stage to the specified position given by the
        target probe number.
        A movement to the z safety position is performed first, before doing the xy positioning.
        Then, z is moved to its specified value.
        Emits a signal when finished and sends the new position and the reached target number.

        :param: int target_position: number of the target probe
        """
        if self.origin is None:
            self.log.warning('Move to target is not possible. Please define the origin.')
            return

        if self.moving:
            self.log.warning('The stage is already moving. No new movement was started.')
            return

        if target_position not in self._probe_grid_dict:
            self.log.warning(
                f'Probe target {target_position} is not available. '
                f'Valid targets are 1 to {self.max_num_probes}.'
            )
            return

        # invert the probe_xy_position_dict
        inv_probe_xy_position_dict = dict((v, k) for k, v in self._probe_xy_position_dict.items())
        x_pos = inv_probe_xy_position_dict[target_position][0]
        y_pos = inv_probe_xy_position_dict[target_position][1]
        z_pos = self.origin[2]
        position = (x_pos, y_pos, z_pos)

        axis_label = self._axis_labels
        pos_dict = dict(zip(axis_label, position))

        # separate into in-plane and z movements
        pos_dict_xy = {
            self.first_axis_label: pos_dict[self.first_axis_label],
            self.second_axis_label: pos_dict[self.second_axis_label],
        }
        pos_dict_z = {self.third_axis_label: pos_dict[self.third_axis_label]}

        self.go_to_target = True  # movement initiated by start_move_to_target
        self.move_stage = False
        self.target_position = target_position  # keep accessible until movement is finished
        self._start_safety_sequence(pos_dict_xy, pos_dict_z)

        # # do the z safety movement
        # self._robot.move_abs({'z': self.z_safety_pos})
        # ready = self._robot.get_status('z')['z']
        # while not ready:
        #     sleep(0.5)
        #     ready = self._robot.get_status('z')['z']
        #     # or use wait for idle (waitontarget) as non interface method .. or add it to the interface
        #
        # # start the xy movement of the translation stage
        # self._robot.move_abs(pos_dict_xy)
        #
        # # start a worker thread to monitor the xy movement
        # worker = xyMoveWorker(pos_dict_xy, pos_dict_z)
        # worker.signals.sigxyStepFinished.connect(self.move_xy_stage_loop)
        # self.threadpool.start(worker)

    def _start_safety_sequence(self, pos_dict_xy, pos_dict_z):
        """Start the z safety movement and schedule non-blocking status polling.

        :param dict pos_dict_xy: Final first- and second-axis target positions.
        :param dict pos_dict_z: Final third-axis target position.
        """
        self.moving = True
        self._movement_id += 1
        movement_id = self._movement_id

        # move to z safety position before making the xy movement
        movement_started = self._robot.move_abs(
            {self.third_axis_label: self.z_safety_pos}
        )
        if not movement_started:
            self._movement_failed('Unable to start the z safety movement.')
            return

        worker = safetyMoveWorker(
            pos_dict_xy, pos_dict_z, movement_id, self.poll_interval
        )
        worker.signals.sigSafetyStepFinished.connect(self.move_safety_stage_loop)
        self.threadpool.start(worker)

    @QtCore.Slot(dict, dict, int)
    def move_safety_stage_loop(self, pos_dict_xy, pos_dict_z, movement_id):
        """Poll the z safety movement before starting the in-plane movement.

        The method ignores callbacks from older movement sequences. While the
        safety axis is moving it emits position updates and schedules another
        polling worker. Once the safety position is reached, the first and
        second axes are moved together.

        :param dict pos_dict_xy: Final first- and second-axis target positions.
        :param dict pos_dict_z: Final third-axis target position.
        :param int movement_id: Identifier of the movement being polled.
        """
        if movement_id != self._movement_id or not self.moving:
            return

        new_position = self.get_position()
        self.sigUpdatePosition.emit(new_position)
        ready = self._robot.get_status([self.third_axis_label])[self.third_axis_label]

        if not ready:
            worker = safetyMoveWorker(
                pos_dict_xy, pos_dict_z, movement_id, self.poll_interval
            )
            worker.signals.sigSafetyStepFinished.connect(self.move_safety_stage_loop)
            self.threadpool.start(worker)
            return

        # start the xy movement of the translation stage
        movement_started = self._robot.move_abs(pos_dict_xy)
        if not movement_started:
            self._movement_failed('Unable to start the in-plane movement.')
            return

        # start a worker thread to monitor the xy movement
        worker = xyMoveWorker(
            pos_dict_xy, pos_dict_z, movement_id, self.poll_interval
        )
        worker.signals.sigxyStepFinished.connect(self.move_xy_stage_loop)
        self.threadpool.start(worker)

    @QtCore.Slot(dict, dict, int)
    def move_xy_stage_loop(self, pos_dict_xy, pos_dict_z, movement_id):
        """Poll the in-plane movement and start the final third-axis movement.

        Current coordinates are emitted on every poll. The connected hardware
        on-target states are used instead of hardcoded positional tolerances,
        allowing the same method to work with both the real PI stage and the
        dummy implementation and with arbitrary configured axis labels.

        :param dict pos_dict_xy: First- and second-axis target positions.
        :param dict pos_dict_z: Final third-axis target position.
        :param int movement_id: Identifier of the movement being polled.
        """
        if movement_id != self._movement_id or not self.moving:
            return

        # compare the current position with the target position
        new_position = self.get_position()
        status = self._robot.get_status(
            [self.first_axis_label, self.second_axis_label]
        )
        self.sigUpdatePosition.emit(new_position)

        if not all(status[label] for label in pos_dict_xy):
            # enter in a loop until xy position reached
            worker = xyMoveWorker(
                pos_dict_xy, pos_dict_z, movement_id, self.poll_interval
            )
            worker.signals.sigxyStepFinished.connect(self.move_xy_stage_loop)
            self.threadpool.start(worker)
        else:
            # xy position reached, start now the z movement
            self.start_move_z_stage(pos_dict_z, movement_id)

    def start_move_z_stage(self, pos_dict_z, movement_id=None):
        """Start the final third-axis movement and its polling worker.

        :param dict pos_dict_z: Dictionary containing the configured third-axis
            label and its target value.
        :param int movement_id: Optional identifier of the active movement.
            The current identifier is used when omitted.
        """
        if movement_id is None:
            movement_id = self._movement_id

        if movement_id != self._movement_id or not self.moving:
            return

        # start the z movement of the translation stage
        movement_started = self._robot.move_abs(pos_dict_z)
        if not movement_started:
            self._movement_failed('Unable to start the final z movement.')
            return

        # start a worker thread to monitor the z movement
        worker = zMoveWorker(pos_dict_z, movement_id, self.poll_interval)
        worker.signals.sigzStepFinished.connect(self.move_z_stage_loop)
        self.threadpool.start(worker)

    @QtCore.Slot(dict, int)
    def move_z_stage_loop(self, pos_dict_z, movement_id):
        """Poll the final third-axis movement and emit completion signals.

        Current coordinates are emitted on every poll. When the hardware
        reports the third axis on target, the final position is read and the
        completion signal corresponding to the original movement request is
        emitted.

        :param dict pos_dict_z: Third-axis target position.
        :param int movement_id: Identifier of the movement being polled.
        """
        if movement_id != self._movement_id or not self.moving:
            return

        # compare the current position with the target position
        new_position = self.get_position()
        self.sigUpdatePosition.emit(new_position)
        ready = self._robot.get_status([self.third_axis_label])[self.third_axis_label]

        if not ready:
            # enter in a loop until z position reached
            worker = zMoveWorker(pos_dict_z, movement_id, self.poll_interval)
            worker.signals.sigzStepFinished.connect(self.move_z_stage_loop)
            self.threadpool.start(worker)
        else:
            self._robot.wait_for_idle()
            new_pos = self.get_position()

            # send the signal to the GUI depending on which button triggered the stage movement
            if self.move_stage:
                self.sigStageMoved.emit(new_pos)
                self.move_stage = False
            elif self.go_to_target:
                self.sigStageMovedToTarget.emit(new_pos, self.target_position)
                self.go_to_target = False
            self.moving = False

    def _movement_failed(self, message):
        """Abort the current movement sequence after a hardware start failure."""
        self.moving = False
        self._movement_id += 1
        try:
            self._robot.abort()
        except Exception as exc:
            self.log.warning(f'Failed to abort movement after startup failure: {exc}')

        self.move_stage = False
        self.go_to_target = False
        self.log.warning(message)

        pos = self.get_position()
        self.sigStageStopped.emit(pos)

    def abort_movement(self):
        """Abort the active stage movement and emit the reached position.

        Outstanding polling callbacks are invalidated so that they cannot
        restart a later part of the movement sequence after the abort.
        """
        self.moving = False
        self._movement_id += 1
        self._robot.abort()

        # reset all flags
        self.move_stage = False
        self.go_to_target = False
        self.log.warning('Movement aborted!')

        pos = self.get_position()
        self.sigStageStopped.emit(pos)

    def get_position(self):
        """ This method retrieves the current stage position from the hardware and does formatting of the return value.

        :return: float tuple: position (x, y, z) or (r, phi, z)
        """
        axis_labels = self._axis_labels
        position = self._robot.get_pos(list(axis_labels))
        return tuple(position[label] for label in axis_labels)

# ----------------------------------------------------------------------------------------------------------------------
# Methods to handle the user interface state
# ----------------------------------------------------------------------------------------------------------------------

    def disable_positioning_actions(self):
        """Disable positioning actions, for example while a task is running."""
        self.sigDisablePositioningActions.emit()

    def enable_positioning_actions(self):
        """Re-enable positioning actions, for example after a task finishes."""
        self.sigEnablePositioningActions.emit()
