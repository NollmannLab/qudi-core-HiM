# -*- coding: utf-8 -*-

"""Experiment configurator logic.

This module loads experiment definitions, stores the values entered in the configurator GUI, and writes
the resulting task configuration to YAML. It also provides the list models used by the imaging-sequence editor.

Three different configuration layers are involved:

1. Global Qudi configuration
   This is the setup-specific Qudi configuration used to activate the logic and GUI modules. It declares
   the directory containing experiment definitions, lists which definition files are enabled on this setup,
   supplies setup-wide defaults such as data paths, and connects optional hardware logic modules. It does
   not contain the parameter values for a particular experiment run.

2. Experiment-definition YAML file
   This is one reusable YAML file per experiment type. It describes the form to present to the user:
   the displayed experiment name, a description, the default output filename, the available fields,
   their defaults, whether they are required, and whether they are visible. A definition may use
   ``default_from`` to obtain a setup-specific default from the global Qudi configuration.

3. Generated experiment configuration
   This is the YAML file produced by the GUI after the user fills in the form. It contains the selected
   experiment name and the resulting field values. It is the file consumed by the corresponding task.

Adding a new experiment
-----------------------
1. Create a new experiment-definition YAML file inside the directory configured
   by ``experiment_definitions_directory``. For example::

        experiment: sequential_injections_sd
        description: Configure a fluidics experiment consisting of buffer injections, probe injections, and incubation steps.
        output_filename: fluidics_task_SD.yaml

        sections:
          documents: true

        fields:
          injections_path:
            required: true
            default: ""

   Use ``default`` for a literal default value. Use ``default_from`` for a
   setup-dependent value, for example::

       save_path:
         default_from: default_path_imagedata
         required: true

2. Enable that definition in the global Qudi configuration. The ``experiments``
   option contains definition filenames, not experiment names:

       experiments_configurator_logic:
         module.Class: experiments_setup.experiment_configurator_logic.ExpConfigLogic
         connect:
          camera_logic: 'camera_logic'
          laser_logic: 'laser_control_logic'
          filter_logic: 'filter_wheel_logic'
         options:
           experiment_definitions_directory: /path/to/experiment_definitions
           experiments:
             - fluidics_ramm.yaml
             - hi_m_ramm.yaml
           supported fileformats:
             - tif
             - npy
             - h5
           default path imagedata: /path/to/local/data
           default network path: /path/to/network/data

   The hardware connectors are optional and may be omitted when the setup does not provide the corresponding module.

3. Reactivate the logic and GUI modules, or restart Qudi. The logic reads the enabled definition files
   during activation and the GUI fills its experiment selector from the loaded ``experiment`` values.

4. Select the new experiment and verify its fields, defaults, required-field validation, output filename,
   and saved YAML content.

No Python change is needed when the definition only uses fields already known by the GUI. A new field requires a widget
in the ``.ui`` file, entries in ``FIELD_SECTIONS`` and ``FIELD_WIDGETS``, a widget-to-logic signal connection, a logic
update method, and support in ``update_entries``. A new imaging-sequence format also requires corresponding model-handling code.

Author: F. Barho. Adapted to qudi-core by JB Fiche using chatGPT
Created 2021-02-17; reformatted 2026-07-31.

-----------------------------------------------------------------------------------
qudi-core is free software: you can redistribute it and/or modify it under the terms of the GNU General Public License
as published by the Free Software Foundation, either version 3 of the License, or (at your option) any later version.

Qudi is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU General Public License for more details.

You should have received a copy of the GNU General Public License along with Qudi. If not, see <http://www.gnu.org/licenses/>.
-----------------------------------------------------------------------------------
"""

import os
import yaml

from copy import deepcopy

from qtpy import QtCore
from qudi.core.module import LogicBase
from qudi.core.configoption import ConfigOption
from qudi.core.connector import Connector


# ======================================================================================================================
# Child class of QAbstractListModel for List View
# ======================================================================================================================

class ImagingSequenceModel(QtCore.QAbstractListModel):
    """Flat Qt list model for standard imaging-sequence entries.

    Each item is stored as ``(lightsource, intensity)`` and rendered as one row in
    the configurator list view."""
    def __init__(self, *args, items=None, **kwargs):
        """Initialize the model.

        Args:
            items: Optional iterable of pre-existing ``(lightsource, intensity)``
                entries. A new empty list is created when omitted.
        """
        super(ImagingSequenceModel, self).__init__(*args, **kwargs)
        self.items = items or []

    def data(self, index, role):
        """Return the text displayed for one model index.

        Args:
            index: Index of the requested imaging-sequence entry.
            role: Qt item-data role.

        Returns:
            A formatted ``"source: intensity"`` string for ``DisplayRole``;
            otherwise ``None``.
        """
        if role == QtCore.Qt.DisplayRole:
            source, intens = self.items[index.row()]
            return f'{source}: {intens}'

    def rowCount(self, index):
        """Return the number of imaging-sequence entries.

        The model is flat, so the parent index is ignored.
        """
        return len(self.items)


class ImagingSequenceModelTimelapseRAMM(QtCore.QAbstractListModel):
    """Flat Qt list model for RAMM timelapse imaging entries.

    Each item is a mapping containing ``lightsource``, ``intensity``,
    ``num_z_planes``, and ``z_step``."""
    def __init__(self, *args, items=None, **kwargs):
        """Initialize the RAMM timelapse model with optional entries."""
        super(ImagingSequenceModelTimelapseRAMM, self).__init__(*args, **kwargs)
        self.items = items or []

    def data(self, index, role):
        """Return the formatted display text for one RAMM timelapse entry."""
        if role == QtCore.Qt.DisplayRole:
            source, intens, num_z_planes, z_step = self.items[index.row()].values()
            return f"laserline: {source}, intensity: {intens}, num_z_planes: {num_z_planes}, z_step: {z_step}"

    def rowCount(self, index):
        """Return the number of RAMM timelapse entries."""
        return len(self.items)


class ImagingSequenceModelTimelapsePALM(QtCore.QAbstractListModel):
    """Flat Qt list model for PALM timelapse imaging entries.

    Each item is a mapping containing ``lightsource``, ``intensity``,
    ``num_z_planes``, ``z_step``, and ``filter_pos``."""
    def __init__(self, *args, items=None, **kwargs):
        """Initialize the PALM timelapse model with optional entries."""
        super(ImagingSequenceModelTimelapsePALM, self).__init__(*args, **kwargs)
        self.items = items or []

    def data(self, index, role):
        """Return the formatted display text for one PALM timelapse entry."""
        if role == QtCore.Qt.DisplayRole:
            source, intens, num_z_planes, z_step, filter_pos = self.items[index.row()].values()
            return f"laserline: {source}, intensity: {intens}, num_z_planes: {num_z_planes}, z_step: {z_step}," \
                   f"filter_pos: {filter_pos}"

    def rowCount(self, index):
        """Return the number of PALM timelapse entries."""
        return len(self.items)


# ======================================================================================================================
# Logic class
# ======================================================================================================================

class ExpConfigLogic(LogicBase):
    """Manage experiment definitions and the active experiment configuration.

    At activation, the module loads the enabled definition files from disk, builds setup-dependent laser
    and filter choices, and creates the imaging-sequence models. The GUI then uses this logic to initialize
    defaults, update individual values, validate required fields, load saved configurations, and write task
    configuration files.

    The optional camera, laser, and filter-wheel connectors are only needed for reading live hardware values
    or populating setup-dependent choices."""

    # define connectors to logic modules
    camera_logic = Connector(name='camera_logic', interface='CameraLogic', optional=True)
    laser_logic = Connector(name='laser_logic', interface='LaserControlLogic', optional=True)
    filter_logic = Connector(name='filter_logic', interface='FilterWheelLogic', optional=True)

    # signals
    sigConfigDictUpdated = QtCore.Signal()
    sigImagingListChanged = QtCore.Signal()
    sigConfigLoaded = QtCore.Signal()
    sigUpdateListModel = QtCore.Signal(int)

    # config options
    experiment_definitions_directory = ConfigOption("experiment_definitions_directory", missing="error")
    experiments = ConfigOption('experiments', missing="warn", default=[])
    supported_fileformats = ConfigOption('supported fileformats')
    default_path_imagedata = ConfigOption('default path imagedata')
    default_network_path = ConfigOption('default network path')

    # attributes
    _experiment_definitions = {}
    experiment_labels = []
    config_dict = {}
    _camera_logic = None
    _laser_logic = None
    _filter_logic = None
    filters = None
    lasers = None
    img_sequence_model = None
    is_timelapse_ramm = False
    is_timelapse_palm = False

    def on_activate(self):
        """Initialize setup-dependent state and load enabled experiment definitions.

        Optional hardware connectors are resolved first. Available laser and filter
        names are collected when the corresponding modules are connected. The three
        imaging-sequence models are then created and the definition registry is loaded
        from the files listed in the global Qudi configuration.
        """
        self._camera_logic = self.camera_logic()
        self._laser_logic = self.laser_logic()
        self._filter_logic = self.filter_logic()

        # prepare the items that will be displayed in the ComboBoxes on the GUI
        self.lasers = []
        if self._laser_logic is not None:
            laser_dict = self._laser_logic.laser_dict
            self.lasers = [wavelength for wavelength in laser_dict]

        self.filters = []
        if self._filter_logic  is not None:
            filter_dict = self._filter_logic.get_filter_dict()
            self.filters = [filter['name'] for filter in filter_dict.values()]

        self.img_sequence_model = ImagingSequenceModel()
        self.img_sequence_model_timelapse_ramm = ImagingSequenceModelTimelapseRAMM()
        self.img_sequence_model_timelapse_palm = ImagingSequenceModelTimelapsePALM()

        # add an additional entry to the experiment selector combobox with placeholder text
        self._load_experiment_definitions()

    def on_deactivate(self):
        """Deactivate the module.

        The configurator currently owns no external resources that require explicit
        cleanup.
        """
        pass

# ----------------------------------------------------------------------------------------------------------------------
# Check instruments availability
# ----------------------------------------------------------------------------------------------------------------------

    @property
    def camera_available(self) -> bool:
        """Return ``True`` when camera logic is connected."""
        return self._camera_logic is not None

    @property
    def laser_available(self) -> bool:
        """Return ``True`` when laser-control logic is connected."""
        return self._laser_logic is not None

    @property
    def filterwheel_available(self) -> bool:
        """Return ``True`` when filter-wheel logic is connected."""
        return self._filter_logic is not None

# ----------------------------------------------------------------------------------------------------------------------
# Methods to load template file for experiments
# ----------------------------------------------------------------------------------------------------------------------
    @property
    def experiment_definitions(self):
        """Return a shallow copy of the loaded definition registry.

        The dictionary is keyed by the human-readable ``experiment`` value stored in
        each definition file.
        """
        return dict(self._experiment_definitions)

    def load_config_file(self, path):
        """Load a previously generated experiment configuration.

        The saved values are overlaid on the defaults from the matching experiment
        definition. The appropriate imaging-sequence model is restored and
        ``sigConfigLoaded`` is emitted so the GUI can select the experiment and display
        the loaded values.

        Args:
            path: Path to the generated YAML configuration file.

        Raises:
            ValueError: If the YAML root is not a mapping, the ``experiment`` key is
                missing, or the referenced experiment is not enabled on this setup.
        """
        with open(path, "r", encoding="utf-8") as stream:
            loaded_config = yaml.safe_load(stream)

        if not isinstance(loaded_config, dict):
            raise ValueError("The experiment configuration must contain a YAML mapping.")

        experiment = loaded_config.get("experiment")

        if not experiment:raise ValueError("The configuration does not define an experiment.")

        if experiment not in self._experiment_definitions:
            raise ValueError(f"Experiment {experiment} is not available on this setup.")

        definition = self._experiment_definitions[experiment]

        # Begin with the definition defaults.
        self.config_dict = self._get_definition_defaults(definition)

        # Replace defaults with values loaded from the file.
        self.config_dict.update(loaded_config)
        self.current_experiment = experiment
        self._restore_imaging_sequence_model()
        self.log.info(f"Experiment configuration loaded from {path}")
        self.sigConfigLoaded.emit()

    def init_config_from_definition(self, experiment: str,) -> None:
        """Start a fresh configuration for an enabled experiment.

        Defaults are read from the experiment definition, all imaging-sequence models
        are cleared, and the timelapse mode flags are reset.

        Args:
            experiment: Human-readable experiment name used as a key in the loaded
                definition registry.

        Raises:
            KeyError: If no enabled definition matches ``experiment``.
        """

        try:
            definition = self._experiment_definitions[experiment]
        except KeyError as exc:
            raise KeyError(f"No experiment definition found for {experiment!r}.") from exc

        self.config_dict = self._get_definition_defaults(definition)

        self.current_experiment = experiment
        self.img_sequence_model.items = []
        self.img_sequence_model_timelapse_ramm.items = []
        self.img_sequence_model_timelapse_palm.items = []

        self.is_timelapse_ramm = False
        self.is_timelapse_palm = False

    def _load_experiment_definitions(self) -> None:
        """Load and validate all definition files enabled by Qudi config.

        Relative filenames from the ``experiments`` option are resolved against
        ``experiment_definitions_directory``. Each file must contain a YAML mapping with
        an ``experiment`` name, a ``fields`` mapping, and an ``output_filename``.
        Experiment names must be unique.

        Raises:
            FileNotFoundError: If the definition directory or an enabled file is
                missing.
            TypeError: If a definition or its ``fields`` entry has the wrong type.
            ValueError: If required metadata is missing or an experiment name is
                duplicated.
        """
        directory = os.path.abspath(os.path.expanduser(self.experiment_definitions_directory))

        if not os.path.isdir(directory):
            raise FileNotFoundError(f"Experiment-definition directory not found: {directory}")

        self._experiment_definitions = {}
        self.experiment_labels = []

        for definition_filename in self.experiments:
            definition_path = str(definition_filename)

            if not os.path.isabs(definition_path):
                definition_path = os.path.join(directory, definition_path)

            if not os.path.isfile(definition_path):
                raise FileNotFoundError(f"Experiment-definition file not found: {definition_path}")

            with open(definition_path, "r", encoding="utf-8") as stream:
                definition = yaml.safe_load(stream)

            if not isinstance(definition, dict):
                raise TypeError(f"Experiment definition must contain a YAML mapping: {definition_path}")

            experiment = definition.get("experiment")

            if not experiment:
                raise ValueError(f"Experiment definition has no 'experiment' entry: {definition_path}")

            experiment = str(experiment)

            if experiment in self._experiment_definitions:
                raise ValueError(f"Experiment {experiment!r} is defined more than once.")
            fields = definition.get("fields", {})

            if not isinstance(fields, dict):
                raise TypeError(f"The 'fields' entry for experiment {experiment!r} must be a dictionary.")

            output_filename = definition.get("output_filename")

            if not output_filename:
                raise ValueError(f"Experiment {experiment!r} has no output filename.")

            self._experiment_definitions[experiment] = definition
            self.experiment_labels.append(experiment)

            self.log.info(f"Loaded experiment definition {experiment!r} from {definition_path}")

    def _get_definition_defaults(self, definition: dict) -> dict:
        """Build a new configuration dictionary from one definition.

        The returned dictionary always contains ``experiment``. Each declared field is
        initialized from either its literal ``default`` or its setup-dependent
        ``default_from`` source.

        Args:
            definition: Parsed experiment-definition mapping.

        Returns:
            A new configuration dictionary containing independent copies of defaults.
        """
        experiment = definition["experiment"]
        fields = definition.get("fields", {})

        config = {"experiment": experiment,}

        for field_name, field_definition in fields.items():
            if field_definition is None:
                field_definition = {}

            if not isinstance(field_definition, dict):
                raise TypeError(f"Definition of field {field_name!r} must be a dictionary.")

            config[field_name] = self._get_field_default(field_definition)

        return config

    def _restore_imaging_sequence_model(self) -> None:
        """Restore imaging-sequence data after loading a saved config.

        All models are cleared first. The model named by the active experiment's
        ``imaging_sequence.model`` setting receives a deep copy of the saved sequence.
        The timelapse flags and ``sigUpdateListModel`` signal are updated accordingly.
        """
        self.img_sequence_model.items = []
        self.img_sequence_model_timelapse_ramm.items = []
        self.img_sequence_model_timelapse_palm.items = []

        sequence = self.config_dict.get("imaging_sequence", [])

        definition = self._experiment_definitions[self.current_experiment]

        imaging_definition = (
            definition
            .get("fields", {})
            .get("imaging_sequence", {})
        )

        if imaging_definition is None:
            imaging_definition = {}

        model_name = imaging_definition.get("model", "standard",)

        self.is_timelapse_ramm = (model_name == "timelapse_ramm")
        self.is_timelapse_palm = (model_name == "timelapse_palm")

        if model_name == "timelapse_ramm":
            self.img_sequence_model_timelapse_ramm.items = (deepcopy(sequence))
            self.sigUpdateListModel.emit(1)

        elif model_name == "timelapse_palm":
            self.img_sequence_model_timelapse_palm.items = (deepcopy(sequence))
            self.sigUpdateListModel.emit(2)

        else:
            self.img_sequence_model.items = deepcopy(sequence)
            self.sigUpdateListModel.emit(0)

    def _get_field_default(self, field_definition: dict):
        """Resolve one field's initial value.

        A literal ``default`` takes precedence. Otherwise, ``default_from`` may refer to
        ``default_path_imagedata`` or ``default_network_path`` from the global Qudi
        configuration. Unknown sources are logged and resolve to ``None``.

        Args:
            field_definition: Parsed metadata for one experiment field.

        Returns:
            A deep copy of the resolved default value, or ``None``.
        """
        if "default" in field_definition:
            return deepcopy(field_definition["default"])

        default_source = field_definition.get("default_from")

        setup_defaults = {
            "default_path_imagedata": self.default_path_imagedata,
            "default_network_path": self.default_network_path,
        }

        if default_source in setup_defaults:
            return deepcopy(setup_defaults[default_source])

        if default_source is not None:
            self.log.warning(f"Unknown default source {default_source!r}.")

        return None

# ----------------------------------------------------------------------------------------------------------------------
# Methods to load / save experiment config files
# ----------------------------------------------------------------------------------------------------------------------

    def save_to_exp_config_file(self, path: str, experiment: str, filename=None,) -> None:
        """Validate and save the active configuration as YAML.

        The default filename comes from the selected experiment definition. A non-empty
        ``filename`` overrides it for the GUI's "Save copy" action. Only fields declared
        by the definition are written, together with the ``experiment`` name. Saving is
        aborted when a required field is empty.

        Args:
            path: Destination directory.
            experiment: Enabled experiment name whose definition controls validation
                and output.
            filename: Optional output filename override.
        """

        definition = self._experiment_definitions.get(experiment)
        if definition is None:
            self.log.error(f"No experiment definition found for {experiment!r}.")
            return

        fields = definition.get("fields", {})
        if not isinstance(fields, dict):
            self.log.error(f"The fields definition for {experiment!r} is invalid.")
            return

        # When saving normally, use the filename from the definition.
        # When saving a copy, the filename selected by the user takes priority.
        if not filename:
            filename = definition.get("output_filename")

        if not filename:
            self.log.error(f"No output filename defined for {experiment!r}.")
            return

        missing_fields = []
        for field_name, field_definition in fields.items():
            if field_definition is None:
                field_definition = {}

            required = field_definition.get("required", False)
            value = self.config_dict.get(field_name)

            if required and self._is_missing_value(value):
                missing_fields.append(field_name)

        if missing_fields:
            missing_text = ", ".join(missing_fields)
            self.log.error(
                f"Experiment configuration not saved. Missing required fields: {missing_text}.")
            return

        saved_config = {"experiment": experiment,}

        for field_name, field_definition in fields.items():
            if field_name in self.config_dict:
                saved_config[field_name] = deepcopy(self.config_dict[field_name] )
            elif isinstance(field_definition, dict):
                saved_config[field_name] = deepcopy(field_definition.get("default"))

        try:
            os.makedirs(path, exist_ok=True)
            complete_path = os.path.join(path, filename,)
            with open(complete_path, "w", encoding="utf-8") as stream:
                yaml.safe_dump(
                    saved_config,
                    stream,
                    default_flow_style=False,
                    sort_keys=False,
                    allow_unicode=True,
                )

        except OSError as error:
            self.log.error(f"Could not save experiment configuration: {error}")
            return

        self.log.info(f"Saved experiment configuration to {complete_path}")

    @staticmethod
    def _is_missing_value(value) -> bool:
        """Return whether a required value should be treated as missing.

        ``None``, blank strings, and empty sequences or mappings are missing. Numeric
        zero and ``False`` are valid values.
        """
        if value is None:
            return True

        if isinstance(value, str):
            return not value.strip()

        if isinstance(value, (list, tuple, dict)):
            return len(value) == 0

        return False

# ----------------------------------------------------------------------------------------------------------------------
# Methods to update dictionary entries on change of associated GUI element
# ----------------------------------------------------------------------------------------------------------------------

    @QtCore.Slot(str)
    def update_sample_name(self, name):
        """Set the sample name and notify configuration listeners."""
        self.config_dict['sample_name'] = name
        self.sigConfigDictUpdated.emit()

    @QtCore.Slot(str)
    def update_mail_address(self, address):
        """Set the notification email address and notify listeners."""
        self.config_dict['email'] = address
        self.sigConfigDictUpdated.emit()

    @QtCore.Slot(int)
    def update_is_dapi(self, state):
        """Convert a Qt check state to the ``dapi`` flag and notify listeners."""
        if state == 2:  # Enum Qt::CheckState Checked = 2
            self.config_dict['dapi'] = True
        elif state == 0:  # Unchecked = 0
            self.config_dict['dapi'] = False
        self.sigConfigDictUpdated.emit()

    @QtCore.Slot(int)
    def update_is_rna(self, state):
        """Convert a Qt check state to the ``rna`` flag and notify listeners."""
        if state == 2:  # Enum Qt::CheckState Checked = 2
            self.config_dict['rna'] = True
        elif state == 0:  # Unchecked = 0
            self.config_dict['rna'] = False
        self.sigConfigDictUpdated.emit()

    @QtCore.Slot(int)
    def update_data_transfer(self, state):
        """Convert a Qt check state to the data-transfer flag and notify listeners."""
        if state == 2:  # Enum Qt::CheckState Checked = 2
            self.config_dict['transfer_data'] = True
        elif state == 0:  # Unchecked = 0
            self.config_dict['transfer_data'] = False
        self.sigConfigDictUpdated.emit()

    @QtCore.Slot(float)
    def update_exposure(self, value):
        """Set the camera exposure value and notify configuration listeners."""
        self.config_dict['exposure'] = value
        # update the gui in case this method was called from the ipython console
        self.sigConfigDictUpdated.emit()

    @QtCore.Slot(int)
    def update_gain(self, value):
        """Set the camera gain value and notify configuration listeners."""
        self.config_dict['gain'] = value
        self.sigConfigDictUpdated.emit()

    @QtCore.Slot(int)
    def update_frames(self, value):
        """Set the number of frames per acquisition and notify listeners."""
        self.config_dict['num_frames'] = value
        self.sigConfigDictUpdated.emit()

    @QtCore.Slot(int)
    def update_filterpos(self, index):
        """Store the one-based filter position selected by the zero-based combo box."""
        self.config_dict['filter_pos'] = index + 1  # zero indexing !
        self.sigConfigDictUpdated.emit()

    @QtCore.Slot(str)
    def update_save_path(self, path):
        """Set the local image-data destination and notify listeners."""
        self.config_dict['save_path'] = path
        self.sigConfigDictUpdated.emit()

    @QtCore.Slot(str)
    def update_save_network_path(self, path):
        """Set the network data destination and notify listeners."""
        self.config_dict['save_network_path'] = path
        self.sigConfigDictUpdated.emit()

    @QtCore.Slot(str)
    def update_fileformat(self, entry):
        """Set the output image format and notify configuration listeners."""
        self.config_dict['file_format'] = entry
        self.sigConfigDictUpdated.emit()

    @QtCore.Slot(int)
    def update_num_z_planes(self, value):
        """Set the number of planes in a z stack and notify listeners."""
        self.config_dict['num_z_planes'] = value
        self.sigConfigDictUpdated.emit()

    @QtCore.Slot(float)
    def update_z_step(self, value):
        """Set the spacing between z planes and notify configuration listeners."""
        self.config_dict['z_step'] = value
        self.sigConfigDictUpdated.emit()

    @QtCore.Slot(int)
    def update_centered_focal_plane(self, state):
        """Convert a Qt check state to the centered-stack flag and notify listeners."""
        if state == 2:  # Enum Qt::CheckState Checked = 2
            self.config_dict['centered_focal_plane'] = True
        elif state == 0:  # Unchecked = 0
            self.config_dict['centered_focal_plane'] = False
        self.sigConfigDictUpdated.emit()

    @QtCore.Slot(str)
    def update_roi_path(self, path):
        """Set the ROI-list file path and notify configuration listeners."""
        self.config_dict['roi_list_path'] = path
        self.sigConfigDictUpdated.emit()

    @QtCore.Slot(str)
    def update_injections_path(self, path):
        """Set the injection-parameter file path and notify listeners."""
        self.config_dict['injections_path'] = path
        self.sigConfigDictUpdated.emit()

    @QtCore.Slot(str)
    def update_dapi_path(self, path):
        """Set the DAPI-data path and notify configuration listeners."""
        self.config_dict['dapi_path'] = path
        self.sigConfigDictUpdated.emit()

    @QtCore.Slot(str)
    def update_zen_ref_images_path(self, path):
        """Set the ZEN autofocus reference-image path and notify listeners."""
        self.config_dict['zen_ref_images_path'] = path
        self.sigConfigDictUpdated.emit()

    @QtCore.Slot(str)
    def update_zen_saving_path(self, path):
        """Set the ZEN data-output path and notify configuration listeners."""
        self.config_dict['zen_saving_path'] = path
        self.sigConfigDictUpdated.emit()

    @QtCore.Slot(float)
    def update_correlation_threshold(self, corr):
        """Set the ZEN autofocus correlation threshold and notify listeners."""
        self.config_dict['correlation_threshold'] = corr
        self.sigConfigDictUpdated.emit()

    @QtCore.Slot(str)
    def update_axial_calibration_path(self, path):
        """Set the axial-calibration file path and notify listeners."""
        self.config_dict['axial_calibration_path'] = path
        self.sigConfigDictUpdated.emit()

    @QtCore.Slot(float)
    def update_illumination_time(self, value):
        """Set the photobleaching illumination duration and notify listeners."""
        self.config_dict['illumination_time'] = value
        self.sigConfigDictUpdated.emit()

    @QtCore.Slot(int)
    def update_num_iterations(self, value):
        """Set the number of timelapse iterations and notify listeners."""
        self.config_dict['num_iterations'] = value
        self.sigConfigDictUpdated.emit()

    @QtCore.Slot(int)
    def update_time_step(self, value):
        """Set the interval between timelapse iterations and notify listeners."""
        self.config_dict['time_step'] = value
        self.sigConfigDictUpdated.emit()

    @QtCore.Slot(str, float, int, float, int)
    def add_entry_to_imaging_list(self, lightsource, intensity, num_z_planes=None, z_step=None, filter_pos=None):
        """Append an entry to the active imaging-sequence model.

        Standard sequences store ``(lightsource, intensity)`` tuples. RAMM and PALM
        timelapse sequences store mappings that also contain per-entry stack settings,
        and PALM entries additionally contain a filter position. ``config_dict`` is
        updated to reference the active model contents and the GUI is notified.
        """
        if self.is_timelapse_ramm:
            self.img_sequence_model_timelapse_ramm.items.append(
                {'lightsource': lightsource, 'intensity': intensity, 'num_z_planes': num_z_planes, 'z_step': z_step})
            self.config_dict['imaging_sequence'] = self.img_sequence_model_timelapse_ramm.items

        elif self.is_timelapse_palm:
            self.img_sequence_model_timelapse_palm.items.append(
                {'lightsource': lightsource, 'intensity': intensity, 'num_z_planes': num_z_planes, 'z_step': z_step,
                 'filter_pos': filter_pos})
            self.config_dict['imaging_sequence'] = self.img_sequence_model_timelapse_palm.items

        else:
            # Access the list via the model.
            self.img_sequence_model.items.append((lightsource, intensity))
            # update the dictionary entry with the current content of the model
            self.config_dict['imaging_sequence'] = self.img_sequence_model.items

        # Trigger refresh of the listview on the GUI:
        # signal layoutChanged cannot be queued over different threads. use custom signal
        self.sigImagingListChanged.emit()

    @QtCore.Slot(QtCore.QModelIndex)
    def delete_entry_from_imaging_list(self, index):
        """Remove the selected entry from the active imaging-sequence model.

        The matching ``config_dict['imaging_sequence']`` value is synchronized and the
        GUI is notified to refresh the list view.
        """
        if self.is_timelapse_ramm:
            del self.img_sequence_model_timelapse_ramm.items[index.row()]
            self.config_dict['imaging_sequence'] = self.img_sequence_model_timelapse_ramm.items

        elif self.is_timelapse_palm:
            del self.img_sequence_model_timelapse_palm.items[index.row()]
            self.config_dict['imaging_sequence'] = self.img_sequence_model_timelapse_palm.items

        else:
            # Remove the item and refresh.
            del self.img_sequence_model.items[index.row()]
            # update the dictionary entry with the current content of the model
            self.config_dict['imaging_sequence'] = self.img_sequence_model.items

        # Trigger refresh of the livtview on the GUI
        self.sigImagingListChanged.emit()

    @QtCore.Slot()
    def delete_imaging_list(self):
        """Clear all in-memory imaging-sequence models and refresh the GUI.

        This method currently clears the models only; callers that require the saved
        configuration value to be cleared must also update
        ``config_dict['imaging_sequence']``.
        """
        self.img_sequence_model.items = []
        self.img_sequence_model_timelapse_ramm.items = []
        self.img_sequence_model_timelapse_palm.items = []
        self.sigImagingListChanged.emit()

# ----------------------------------------------------------------------------------------------------------------------
# Methods to retrieve current values from devices
# ----------------------------------------------------------------------------------------------------------------------

    def get_exposure(self):
        """Read the current exposure from camera logic and copy it into the config."""
        exposure = self._camera_logic.get_exposure()
        self.config_dict['exposure'] = exposure
        self.sigConfigDictUpdated.emit()

    def get_gain(self):
        """Read the current gain from camera logic and copy it into the config."""
        gain = self._camera_logic.get_gain()
        self.config_dict['gain'] = gain
        self.sigConfigDictUpdated.emit()

    def get_filterpos(self):
        """Read the current filter-wheel position and copy it into the config."""
        filterpos = self._filter_logic.get_position()
        self.config_dict['filter_pos'] = filterpos
        self.sigConfigDictUpdated.emit()

    # def init_default_config_dict(self):
    #     """ Initialize the entries of the dictionary with some default values,
    #     to set entries to the form displayed on the GUI on startup.
    #     NB : since the following entries are defined by default, they will not be mandatory for saving the form.
    #     """
    #     # self.config_dict = {}
    #     self.config_dict['dapi'] = False
    #     self.config_dict['rna'] = False
    #     self.config_dict['transfer_data'] = False
    #     self.config_dict['exposure'] = 0.05
    #     self.config_dict['gain'] = 0
    #     self.config_dict['num_frames'] = 1
    #     self.config_dict['filter_pos'] = 1
    #     self.img_sequence_model.items = []
    #     self.img_sequence_model_timelapse_ramm.items = []
    #     self.img_sequence_model_timelapse_palm.items = []
    #     self.config_dict['save_path'] = self.default_path_images
    #     self.config_dict['save_network_path'] = self.default_network_path
    #     self.config_dict['file_format'] = 'tif'
    #     self.config_dict['num_z_planes'] = 1
    #     self.config_dict['centered_focal_plane'] = False
    #     self.config_dict['dapi_path'] = ''
    #     # self.config_dict['zen_ref_images_path'] = ''
    #     # self.config_dict['zen_saving_path'] = ''
    #     self.config_dict['num_iterations'] = 0
    #     self.config_dict['time_step'] = 0
    #     self.config_dict['axial_calibration_path'] = ''
    #     self.config_dict['email'] = None
    #     # add here further dictionary entries that need initialization
    #     self.sigConfigDictUpdated.emit()

    # def save_to_exp_config_file(self, path, experiment, filename=None):
    #     """ Saves the current config_dict to a yml file.
    #
    #     :param: str path: path to directory where the config file is saved
    #     :param: str experiment: name of the experiment that shall be saved.
    #                     For clarity, always append the name of the experimental setup for which the task is destinated.
    #     :param: str filename: name of the config file including the suffix .yml. Default is None.
    #                         filename must only be given when using save copy of config file under a non-default name.
    #
    #     :return: None
    #     """
    #     if not os.path.exists(path):
    #         try:
    #             os.makedirs(path)  # recursive creation of all directories on the path
    #         except Exception as e:
    #             self.log.error(f'Error {e}.')
    #
    #     config_dict = {}
    #
    #     print(f'Experiment = {experiment}')
    #
    #     try:
    #         if experiment == 'Multicolor imaging PALM':
    #             if not filename:
    #                 filename = 'multicolor_imaging_task_PALM.yml'
    #             keys_to_extract = ['sample_name', 'filter_pos', 'exposure', 'gain', 'num_frames', 'save_path',
    #                                'imaging_sequence', 'file_format']
    #             config_dict = {key: self.config_dict[key] for key in keys_to_extract}
    #
    #         elif experiment == 'Multicolor scan PALM':
    #             if not filename:
    #                 filename = 'multicolor_scan_task_PALM.yml'
    #             keys_to_extract = ['sample_name', 'filter_pos', 'exposure', 'gain', 'num_frames', 'save_path',
    #                                'file_format', 'imaging_sequence', 'num_z_planes', 'z_step', 'centered_focal_plane']
    #             config_dict = {key: self.config_dict[key] for key in keys_to_extract}
    #
    #         elif experiment == 'Multicolor scan RAMM':
    #             if not filename:
    #                 filename = 'multicolor_scan_task_RAMM.yml'
    #             keys_to_extract = ['sample_name', 'exposure', 'save_path', 'file_format', 'imaging_sequence',
    #                                'num_z_planes', 'z_step', 'centered_focal_plane']
    #             config_dict = {key: self.config_dict[key] for key in keys_to_extract}
    #
    #         if experiment == 'PAINT RAMM':
    #             if not filename:
    #                 filename = 'PAINT_task_RAMM.yml'
    #             keys_to_extract = ['sample_name', 'exposure', 'save_path', 'imaging_sequence', 'num_z_planes']
    #             config_dict = {key: self.config_dict[key] for key in keys_to_extract}
    #
    #         elif experiment == 'Multicolor scan Airyscan':
    #             if not filename:
    #                 filename = 'multicolor_scan_task_AIRYSCAN.yml'
    #             keys_to_extract = ['imaging_sequence', 'num_z_planes']
    #             config_dict = {key: self.config_dict[key] for key in keys_to_extract}
    #
    #         elif experiment == 'ROI multicolor scan PALM':
    #             if not filename:
    #                 filename = 'ROI_multicolor_scan_task_PALM.yml'
    #             keys_to_extract = ['sample_name', 'filter_pos', 'exposure', 'gain', 'num_frames', 'save_path',
    #                                'file_format', 'imaging_sequence', 'num_z_planes', 'z_step', 'centered_focal_plane',
    #                                'roi_list_path']
    #             config_dict = {key: self.config_dict[key] for key in keys_to_extract}
    #
    #         elif experiment == 'ROI multicolor scan RAMM':
    #             if not filename:
    #                 filename = 'ROI_multicolor_scan_task_RAMM.yml'
    #             keys_to_extract = ['sample_name', 'dapi', 'rna', 'exposure', 'save_path', 'file_format',
    #                                'imaging_sequence', 'num_z_planes', 'z_step', 'roi_list_path',
    #                                'centered_focal_plane']
    #             config_dict = {key: self.config_dict[key] for key in keys_to_extract}
    #
    #         elif experiment == 'ROI multicolor scan Airyscan':
    #             if not filename:
    #                 filename = 'ROI_multicolor_scan_task_AIRYSCAN.yml'
    #             keys_to_extract = ['sample_name', 'dapi', 'rna', 'save_path', 'imaging_sequence', 'num_z_planes',
    #                                'roi_list_path']
    #             config_dict = {key: self.config_dict[key] for key in keys_to_extract}
    #
    #         elif experiment == 'ROI multicolor scan Airyscan confocal':
    #             if not filename:
    #                 filename = 'ROI_multicolor_scan_task_AIRYSCAN_confocal.yml'
    #             keys_to_extract = ['sample_name', 'save_path', 'roi_list_path']
    #             config_dict = {key: self.config_dict[key] for key in keys_to_extract}
    #
    #         elif experiment == 'Fluidics RAMM':
    #             if not filename:
    #                 filename = 'fluidics_task_RAMM.yml'
    #             keys_to_extract = ['injections_path']
    #             config_dict = {key: self.config_dict[key] for key in keys_to_extract}
    #
    #         elif experiment == 'Fluidics Airyscan':
    #             if not filename:
    #                 filename = 'fluidics_task_AIRYSCAN.yml'
    #             keys_to_extract = ['injections_path']
    #             config_dict = {key: self.config_dict[key] for key in keys_to_extract}
    #
    #         elif experiment == 'Hi-M RAMM':
    #             if not filename:
    #                 filename = 'hi_m_task_RAMM.yml'
    #             keys_to_extract = ['sample_name', 'exposure', 'save_path', 'save_network_path', 'transfer_data',
    #                                'file_format', 'imaging_sequence', 'num_z_planes', 'z_step', 'centered_focal_plane',
    #                                'roi_list_path', 'injections_path', 'email']
    #             config_dict = {key: self.config_dict[key] for key in keys_to_extract}
    #
    #         elif experiment == 'Hi-M Airyscan Lumencor':
    #             if not filename:
    #                 filename = 'hi_m_task_AIRYSCAN.yml'
    #                 keys_to_extract = ['sample_name', 'save_path', 'imaging_sequence', 'num_z_planes', 'roi_list_path',
    #                                    'injections_path', 'dapi_path']
    #                 config_dict = {key: self.config_dict[key] for key in keys_to_extract}
    #
    #         elif experiment == 'Hi-M Airyscan Epi':
    #             if not filename:
    #                 filename = 'hi_m_task_AIRYSCAN_epi.yml'
    #                 keys_to_extract = ['sample_name', 'imaging_sequence', 'num_z_planes', 'roi_list_path',
    #                                    'injections_path', 'zen_ref_images_path', 'zen_saving_path',
    #                                    'save_network_path', 'transfer_data', 'email', 'correlation_threshold']
    #                 config_dict = {key: self.config_dict[key] for key in keys_to_extract}
    #
    #         elif experiment == 'Hi-M Autofocus Check Epi':
    #             if not filename:
    #                 filename = 'calibration_task_epi.yml'
    #                 keys_to_extract = ['sample_name', 'num_z_planes', 'roi_list_path', 'zen_ref_images_path',
    #                                    'zen_saving_path', 'save_network_path', 'transfer_data', 'email']
    #                 config_dict = {key: self.config_dict[key] for key in keys_to_extract}
    #
    #         elif experiment == 'Hi-M Airyscan Confocal':
    #             if not filename:
    #                 filename = 'hi_m_task_AIRYSCAN_confocal.yml'
    #                 keys_to_extract = ['sample_name', 'save_path', 'roi_list_path', 'injections_path', 'dapi_path']
    #                 config_dict = {key: self.config_dict[key] for key in keys_to_extract}
    #
    #         elif experiment == 'Photobleaching RAMM':
    #             if not filename:
    #                 filename = 'photobleaching_task_RAMM.yml'
    #             keys_to_extract = ['imaging_sequence', 'roi_list_path', 'illumination_time']
    #             config_dict = {key: self.config_dict[key] for key in keys_to_extract}
    #
    #         elif experiment == 'Photobleaching Airyscan':
    #             if not filename:
    #                 filename = 'photobleaching_task_AIRYSCAN.yml'
    #             keys_to_extract = ['imaging_sequence', 'roi_list_path', 'illumination_time']
    #             config_dict = {key: self.config_dict[key] for key in keys_to_extract}
    #
    #         elif experiment == 'Fast timelapse RAMM':
    #             if not filename:
    #                 filename = 'fast_timelapse_task_RAMM.yml'
    #             keys_to_extract = ['sample_name', 'exposure', 'save_path', 'file_format', 'imaging_sequence',
    #                                'num_z_planes', 'z_step', 'centered_focal_plane', 'roi_list_path', 'num_iterations',
    #                                'axial_calibration_path']
    #             config_dict = {key: self.config_dict[key] for key in keys_to_extract}
    #
    #         elif experiment == 'Hubble RAMM':
    #             if not filename:
    #                 filename = 'hubble_task_RAMM.yml'
    #             keys_to_extract = ['sample_name', 'exposure', 'save_path', 'file_format', 'imaging_sequence',
    #                                'num_z_planes', 'z_step', 'centered_focal_plane', 'roi_list_path',
    #                                'axial_calibration_path']
    #             config_dict = {key: self.config_dict[key] for key in keys_to_extract}
    #
    #         elif experiment == 'Timelapse RAMM':
    #             if not filename:
    #                 filename = 'timelapse_task_RAMM.yml'
    #             keys_to_extract = ['sample_name', 'exposure', 'save_path', 'file_format', 'imaging_sequence',
    #                                'centered_focal_plane', 'roi_list_path', 'num_iterations', 'time_step']
    #             config_dict = {key: self.config_dict[key] for key in keys_to_extract}
    #
    #         elif experiment == 'Timelapse PALM':
    #             if not filename:
    #                 filename = 'timelapse_task_PALM.yml'
    #             keys_to_extract = ['sample_name', 'exposure', 'gain', 'save_path', 'file_format', 'imaging_sequence',
    #                                'centered_focal_plane', 'roi_list_path', 'num_iterations', 'time_step']
    #             config_dict = {key: self.config_dict[key] for key in keys_to_extract}
    #
    #         # add here all additional experiments and select the relevant keys
    #         else:
    #             pass
    #
    #     except KeyError as e:
    #         self.log.warning(f'Experiment configuration not saved. Missing information {e}.')
    #         return
    #
    #     config_dict['experiment'] = experiment
    #     complete_path = os.path.join(path, filename)
    #     print(complete_path)
    #     with open(complete_path, 'w') as file:
    #         yaml.safe_dump(config_dict, file, default_flow_style=False)
    #     self.log.info('Saved experiment configuration to {}'.format(complete_path))

    # def load_config_file(self, path):
    #     """ Loads a configuration file and sets the entries of the config_dict accordingly
    #
    #     :param: str path: complete path to an experiment configuration file
    #     :return: None
    #     """
    #     with open(path, 'r') as stream:
    #         data_dict = yaml.safe_load(stream)
    #
    #     self.config_dict = data_dict
    #
    #     # safety check: is at least the key 'experiment' contained in the file ?
    #     if 'experiment' not in self.config_dict.keys():
    #         self.log.warning('The loaded files does not contain necessary parameters. Configuration not loaded.')
    #         return
    #     else:
    #         self.log.info(f'Configuration loaded from {path}')
    #
    #     if 'imaging_sequence' in self.config_dict.keys():
    #
    #         if self.config_dict['experiment'] == 'Timelapse RAMM':
    #             self.sigUpdateListModel.emit(1)
    #             self.is_timelapse_ramm = True
    #             self.is_timelapse_palm = False
    #             for item in self.config_dict['imaging_sequence']:
    #                 lightsource = item['lightsource']
    #                 intensity = item['intensity']
    #                 num_z_planes = item['num_z_planes']
    #                 z_step = item['z_step']
    #                 self.img_sequence_model_timelapse_ramm.items.append(
    #                     {'lightsource': lightsource, 'intensity': intensity, 'num_z_planes': num_z_planes,
    #                      'z_step': z_step})
    #
    #         elif self.config_dict['experiment'] == 'Timelapse PALM':
    #             self.sigUpdateListModel.emit(2)
    #             self.is_timelapse_palm = True
    #             self.is_timelapse_ramm = False
    #             for item in self.config_dict['imaging_sequence']:
    #                 lightsource = item['lightsource']
    #                 intensity = item['intensity']
    #                 num_z_planes = item['num_z_planes']
    #                 z_step = item['z_step']
    #                 filter_pos = item['filter_pos']
    #                 self.img_sequence_model_timelapse_palm.items.append(
    #                     {'lightsource': lightsource, 'intensity': intensity, 'num_z_planes': num_z_planes,
    #                      'z_step': z_step, 'filter_pos': filter_pos})
    #
    #         else:
    #             self.sigUpdateListModel.emit(0)
    #             self.is_timelapse_ramm = False
    #             self.is_timelapse_palm = False
    #             # synchronize the listviewmodel with the config_dict['imaging_sequence'] entry
    #             self.img_sequence_model.items = self.config_dict['imaging_sequence']
    #
    #     self.sigConfigLoaded.emit()
