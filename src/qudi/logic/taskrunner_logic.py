# -*- coding: utf-8 -*-
"""
This file contains the Qudi task runner module.

Copyright (c) 2021, the qudi developers. See the AUTHORS.md file at the top-level directory of this
distribution and on <https://github.com/Ulm-IQO/qudi-core/>

This file is part of qudi.

Qudi is free software: you can redistribute it and/or modify it under the terms of
the GNU Lesser General Public License as published by the Free Software Foundation,
either version 3 of the License, or (at your option) any later version.

Qudi is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY;
without even the implied warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.
See the GNU Lesser General Public License for more details.

You should have received a copy of the GNU Lesser General Public License along with qudi.
If not, see <https://www.gnu.org/licenses/>.

Modified with Claude code (Anthropic)
"""

import inspect
from functools import partial
from PySide6 import QtCore
from typing import Any, Type, Mapping, List, Dict

from qudi.util.mutex import Mutex
from qudi.core.module import LogicBase
from qudi.core.scripting.moduletask import ModuleTask
from qudi.core.scripting.modulescript import import_module_script
from qudi.core.configoption import ConfigOption
from qudi.core.connector import Connector

try:  # ConnectorList only exists from qudi-core 1.8.0 on
    from qudi.core.connector import ConnectorList
    _CONNECTOR_TYPES = (Connector, ConnectorList)
except ImportError:
    _CONNECTOR_TYPES = (Connector,)


class TaskRunnerLogic(LogicBase):
    """This module keeps a collection of available ModuleTask subclasses (defined by config) and
    respective initialized instances that can be run.
    Handles module connections to tasks and allows monitoring of task states and results.

    Task options (qudi-core-HiM): a task entry may carry an "options:" mapping. Each key must be a
    public class attribute the task already declares (not private, not a method, Connector, Qt
    signal or property); its value replaces the class default on the task instance created for
    each run - the class itself and other tasks are not modified. Invalid options make the
    activation of the task runner fail with a clear error. Typical use: the location of the YAML
    file written by the experiment configurator, which differs between machines.

    Config example:

        task_runner:
            module.Class: 'taskrunner_logic.TaskRunnerLogic'
            options:
                module_tasks:
                    photobleaching:
                        module.Class: 'qudi.tasks.photobleaching.PhotoBleachingSDTask'
                        connect:
                            roi_logic: roi_logic
                            laser_logic: laser_control_logic
                        options:
                            user_config_path: '/path/to/photobleaching_task_sd.yaml'
    """

    _module_task_configs = ConfigOption(name='module_tasks', default=dict(), missing='warn')

    sigTaskStarted = QtCore.Signal(str)  # task name
    sigTaskStateChanged = QtCore.Signal(str, str)  # task name, task state
    sigTaskFinished = QtCore.Signal(str, object, bool)  # task name, result, success flag
    sigTaskProgress = QtCore.Signal(str, str, str)  # task name, step, text (tasks with sigProgress only)
    _sigStartTask = QtCore.Signal(str, dict)  # task name, args, kwargs

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._thread_lock = Mutex()
        self._running_tasks = dict()
        self._configured_task_types = dict()
        self._task_options = dict()  # task name -> validated options applied to each instance
        self._consecutive_activation = False  # Flag indicating consecutive activations

    def on_activate(self) -> None:
        """Initialise task runner."""
        self._running_tasks = dict()
        self._configured_task_types = dict()
        self._task_options = dict()
        for name, task_cfg in self._module_task_configs.items():
            if name in self._configured_task_types:
                raise KeyError(f'Duplicate task name "{name}" encountered in config')
            module, cls = task_cfg['module.Class'].rsplit('.', 1)
            task = import_module_script(module, cls, reload=self._consecutive_activation)
            if not issubclass(task, ModuleTask):
                raise TypeError('Configured task is not a ModuleTask (sub)class')
            options = task_cfg.get('options') or {}
            self._task_options[name] = self._validate_task_options(name, task, options)
            self._configured_task_types[name] = task
        self._sigStartTask.connect(self._run_task, QtCore.Qt.QueuedConnection)
        self._consecutive_activation = True

    @staticmethod
    def _option_attributes(task_type: Type[ModuleTask]) -> List[str]:
        """Names of the class attributes of task_type that may be set through "options:": public,
        not callable (methods, classes), not a Connector, Qt signal or property.
        """
        allowed = list()
        for attr_name in dir(task_type):
            if attr_name.startswith('_'):
                continue
            value = inspect.getattr_static(task_type, attr_name)
            if isinstance(value, (property, QtCore.Signal, QtCore.QMetaObject) + _CONNECTOR_TYPES):
                continue
            if callable(value) or isinstance(value, (staticmethod, classmethod)):
                continue
            allowed.append(attr_name)
        return allowed

    def _validate_task_options(self, name: str, task_type: Type[ModuleTask],
                               options: Any) -> Dict[str, Any]:
        """Check the "options:" of one task entry. Raises with a clear message if they are not a
        mapping with str keys, or if a key is not a settable class attribute of the task.
        """
        if not isinstance(options, Mapping):
            raise TypeError(f'Invalid "options" for task "{name}" ({task_type.__name__}): expected '
                            f'a mapping of attribute names to values, got {type(options).__name__}.')
        allowed = self._option_attributes(task_type)
        for key in options:
            if not isinstance(key, str):
                raise TypeError(f'Invalid option key {key!r} for task "{name}" '
                                f'({task_type.__name__}): option names must be strings.')
            if key not in allowed:
                if key.startswith('_'):
                    reason = 'private attributes cannot be set from the config'
                elif not hasattr(task_type, key):
                    reason = 'the task class declares no such attribute'
                else:
                    reason = 'it is a method, Connector, signal or property, not a plain value'
                raise KeyError(f'Invalid option "{key}" for task "{name}" ({task_type.__name__}): '
                               f'{reason}. Allowed options: {", ".join(allowed) or "none"}.')
        return dict(options)

    def on_deactivate(self) -> None:
        """Shut down task runner."""
        self._sigStartTask.disconnect()
        for task in self._running_tasks.values():
            task.interrupt()
        self._configured_task_types = dict()

    @property
    def running_tasks(self) -> List[str]:
        with self._thread_lock:
            return list(self._running_tasks)

    @property
    def task_states(self) -> Dict[str, str]:
        with self._thread_lock:
            states = dict()
            for task_name in self._configured_task_types:
                try:
                    states[task_name] = self._running_tasks[task_name].state
                except KeyError:
                    states[task_name] = 'stopped'
            return states

    @property
    def configured_task_types(self) -> Dict[str, Type[ModuleTask]]:
        return self._configured_task_types.copy()

    def run_task(self, name: str, arguments: Mapping[str, Any]) -> None:
        with self._thread_lock:
            self._sigStartTask.emit(name, dict(arguments))

    def interrupt_task(self, name: str) -> None:
        """Request that the running ModuleTask called "name" stops as soon as possible.

        This only sets a flag on the task (see ModuleTask.interrupt / ModuleScript.interrupt in
        qudi-core): the task itself must be checking that flag regularly from within its own _run()
        (via self._check_interrupt(), typically through an interruptible wait - see
        tasks/dummy_fluidics_task.py for an example) for this to have any visible effect. A task with
        no interrupt checkpoints, or a long blocking hardware call between two checkpoints, will keep
        running until it reaches the next one.
        """
        with self._thread_lock:
            task = self._running_tasks.get(name, None)
            if task is None:
                self.log.error(f'Cannot interrupt: no ModuleTask with name "{name}" is running.')
                raise RuntimeError(f'No ModuleTask with name "{name}" running')
            self.log.info(f'Interrupt requested for ModuleTask "{name}".')
            task.interrupt()

    @QtCore.Slot(str, dict)
    def _run_task(self, name: str, arguments: Mapping[str, Any]) -> None:
        with self._thread_lock:
            task = self.__init_task(name)
            self.__set_task_arguments(task, arguments)
            self.__activate_connect_task_modules(name, task)
            self.__move_task_into_thread(name, task)
            self.__connect_task_signals(name, task)
            self.__start_task(name, task)
            self.sigTaskStarted.emit(name)

    def _task_finished_callback(self, name: str) -> None:
        """Called every time a task finishes."""
        with self._thread_lock:
            task = self._running_tasks.get(name, None)
            if task is not None:
                task.sigFinished.disconnect()
                task.sigStateChanged.disconnect()
                if hasattr(task, 'sigProgress'):
                    task.sigProgress.disconnect()
                task.disconnect_modules()
                thread_manager = self._qudi_main.thread_manager
                thread_manager.quit_thread(task.thread())
                thread_manager.join_thread(task.thread())

    def _thread_finished_callback(self, name: str) -> None:
        with self._thread_lock:
            task = self._running_tasks.pop(name, None)
            if task is not None:
                self.sigTaskFinished.emit(name, task.result, task.success)

    def _task_state_changed_callback(self, state: str, name: str) -> None:
        self.sigTaskStateChanged.emit(name, state)

    def _task_progress_callback(self, step: str, text: str, name: str) -> None:
        self.sigTaskProgress.emit(name, step, text)

    def __init_task(self, name: str) -> ModuleTask:
        """Create a ModuleTask instance."""
        try:
            if name in self._running_tasks:
                raise RuntimeError(f'ModuleTask "{name}" is already initialized')
            task = self._configured_task_types[name]()
            # Config "options:" override the class defaults on this instance only
            for key, value in self._task_options.get(name, {}).items():
                setattr(task, key, value)
            return task
        except:
            self.log.exception(f'Exception during initialization of ModuleTask "{name}":')
            raise

    def __set_task_arguments(self, task: ModuleTask, arguments: Mapping[str, Any]) -> None:
        """Set arguments for ModuleTask instance."""
        try:
            if not (isinstance(arguments, Mapping) and all(isinstance(a, str) for a in arguments)):
                raise TypeError('ModuleTask kwargs must be mapping with str type keys')
            task.kwargs = arguments
        except:
            self.log.exception(f'Exception during setting of arguments for ModuleTask:')
            raise

    def __activate_connect_task_modules(self, name: str, task: ModuleTask) -> None:
        """Activate and connect all configured module connectors for ModuleTask."""
        try:
            module_manager = self._qudi_main.module_manager
            connect_targets = dict()
            for conn_name, module_name in self._module_task_configs[name]['connect'].items():
                module = module_manager[module_name]
                module.activate()
                connect_targets[conn_name] = module.instance
            task.connect_modules(connect_targets)
        except:
            self.log.exception(f'Exception during modules connection for ModuleTask "{name}":')
            task.disconnect_modules()
            raise

    def __move_task_into_thread(self, name: str, task: ModuleTask) -> None:
        """Create a new QThread via qudi thread manager and move ModuleTask instance into it."""
        try:
            thread = self._qudi_main.thread_manager.get_new_thread(name=f'ModuleTask-{name}')
            if thread is None:
                raise RuntimeError(f'Unable to create QThread with name "ModuleTask-{name}"')
        except RuntimeError:
            self.log.exception('Exception during thread creation:')
            raise
        task.moveToThread(thread)
        thread.started.connect(task.run, QtCore.Qt.QueuedConnection)
        thread.finished.connect(partial(self._thread_finished_callback, name=name))

    def __connect_task_signals(self, name: str, task: ModuleTask) -> None:
        task.sigFinished.connect(partial(self._task_finished_callback, name=name),
                                 QtCore.Qt.QueuedConnection)
        task.sigStateChanged.connect(partial(self._task_state_changed_callback, name=name),
                                     QtCore.Qt.QueuedConnection)
        # progress: only tasks that declare sigProgress (e.g. ProgressModuleTask)
        if hasattr(task, 'sigProgress'):
            task.sigProgress.connect(partial(self._task_progress_callback, name=name),
                                     QtCore.Qt.QueuedConnection)

    def __start_task(self, name: str, task: ModuleTask) -> None:
        self._running_tasks[name] = task
        task.thread().start()
