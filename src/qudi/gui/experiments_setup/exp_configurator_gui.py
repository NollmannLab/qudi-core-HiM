# -*- coding: utf-8 -*-

"""
# Author: F.Barho - adapted to qudi-core by JB Fiche using chatGPT
# Reformated: 2026-07-31
This module contains a GUI that allows to create an experiment config file for a Task.

qudi-core is free software: you can redistribute it and/or modify it under the terms of the GNU General Public License
as published by the Free Software Foundation, either version 3 of the License, or (at your option) any later version.

Qudi is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU General Public License for more details.

You should have received a copy of the GNU General Public License along with Qudi. If not, see <http://www.gnu.org/licenses/>.
"""

import os
from qtpy import QtCore
from qtpy import QtWidgets
from qtpy import uic

from qudi.core.module import GuiBase
from qudi.core.connector import Connector
from qudi.core.configoption import ConfigOption


class ExpConfiguratorWindow(QtWidgets.QMainWindow):
    """ Class defined for the main window (not the module).

    """
    def __init__(self, ui_filename):
        # Get the path to the *.ui file
        this_dir = os.path.dirname(__file__)
        ui_file = os.path.join(this_dir, ui_filename)

        # Load it
        super().__init__()
        uic.loadUi(ui_file, self)

        self.show()


class ExpConfiguratorGUI(GuiBase):
    """ GUI module that helps the user to define the configuration file for the different types of experiments (=tasks).

    Example config for copy-paste:

    Experiment Configurator:
        module.Class: 'experiment_configurator.exp_configurator_gui.ExpConfiguratorGUI'
        default_location_qudi_files: '/home/barho/qudi_files'
        connect:
            exp_config_logic: 'exp_config_logic'
    """

    SECTION_VISIBILITY_METHODS = {
        "general": "set_visibility_general_settings",
        "camera": "set_visibility_camera_settings",
        "filter": "set_visibility_filter_settings",
        "imaging": "set_visibility_imaging_settings",
        "save": "set_visibility_save_settings",
        "scan": "set_visibility_scan_settings",
        "documents": "set_visibility_documents_settings",
        "prebleaching": "set_visibility_prebleaching_settings",
        "timelapse": "set_visibility_timelapse_settings",
        "zen_security": "set_visibility_ZEN_security_settings",
    }

    FIELD_SECTIONS = {
        "sample_name": "general",
        "dapi": "general",
        "rna": "general",
        "email": "general",

        "exposure": "camera",
        "gain": "camera",
        "num_frames": "camera",

        "filter_pos": "filter",

        "imaging_sequence": "imaging",

        "save_path": "save",
        "save_network_path": "save",
        "transfer_data": "save",
        "file_format": "save",
        "zen_saving_path": "save",

        "num_z_planes": "scan",
        "z_step": "scan",
        "centered_focal_plane": "scan",

        "roi_list_path": "documents",
        "injections_path": "documents",
        "dapi_path": "documents",

        "illumination_time": "prebleaching",

        "num_iterations": "timelapse",
        "time_step": "timelapse",
        "axial_calibration_path": "timelapse",

        "zen_ref_images_path": "zen_security",
        "correlation_threshold": "zen_security",
    }

    FIELD_WIDGETS = {
        "sample_name": (
            "sample_name_Label",
            "sample_name_LineEdit",
        ),

        "dapi": (
            "dapi_CheckBox",
        ),

        "rna": (
            "rna_CheckBox",
        ),

        "email": (
            "mail_Label",
            "mail_LineEdit",
        ),

        "exposure": (
            "exposure_Label",
            "exposure_DSpinBox",
            "get_exposure_PushButton",
        ),

        "gain": (
            "gain_Label",
            "gain_SpinBox",
            "get_gain_PushButton",
        ),

        "num_frames": (
            "num_frames_Label",
            "num_frames_SpinBox",
        ),

        "filter_pos": (
            "filterpos_Label",
            "filterpos_ComboBox",
            "get_filterpos_PushButton",
        ),

        "imaging_sequence": (
            "imaging_sequence_Label",
            "imaging_sequence_ListView",
            "laser_ComboBox",
            "laser_intensity_DSpinBox",
            "add_entry_PushButton",
            "delete_entry_PushButton",
            "delete_all_PushButton",
        ),

        "save_path": (
            "save_path_Label",
            "save_path_LineEdit",
        ),

        "save_network_path": (
            "save_remote_path_Label",
            "save_network_path_LineEdit",
        ),

        "transfer_data": (
            "TransferData_checkBox",
        ),

        "file_format": (
            "fileformat_Label",
            "fileformat_ComboBox",
        ),

        "num_z_planes": (
            "num_z_planes_Label",
            "num_z_planes_SpinBox",
        ),

        "z_step": (
            "z_step_Label",
            "z_step_DSpinBox",
        ),

        "centered_focal_plane": (
            "centered_focal_plane_CheckBox",
        ),

        "roi_list_path": (
            "roi_list_path_Label",
            "roi_list_path_LineEdit",
            "load_roi_PushButton",
        ),

        "injections_path": (
            "injections_list_Label",
            "injections_list_LineEdit",
            "load_injections_PushButton",
        ),

        "dapi_path": (
            "dapi_path_Label",
            "dapi_data_LineEdit",
            "load_dapi_PushButton",
        ),

        "illumination_time": (
            "illumination_time_Label",
            "illumination_time_DSpinBox",
        ),

        "num_iterations": (
            "num_iterations_Label",
            "num_iterations_SpinBox",
        ),

        "time_step": (
            "time_step_Label",
            "time_step_SpinBox",
        ),

        "axial_calibration_path": (
            "dz_calibration_label",
            "axial_calibration_path_lineEdit",
            "load_dz_calibration_pushButton",
        ),

        "zen_ref_images_path": (
            "reference_image_folder_Label",
            "reference_images_lineEdit",
            "reference_images_pushButton",
        ),

        "zen_saving_path": (
            "Zen_saving_folder_Label",
            "Zen_saving_folder_lineEdit",
            "Zen_saving_folder_pushButton",
        ),

        "correlation_threshold": (
            "Correlation_threshold_Label",
            "Zen_correlation_DSpinBox",
        ),
    }

    # define the default language option as English (to make sure all float have a point as a separator)
    QtCore.QLocale.setDefault(QtCore.QLocale("English"))

    # connector to logic module
    exp_logic = Connector(name='experiment_logic', interface='ExpConfigLogic')

    # config options
    default_location = ConfigOption('default_path', missing='error')
    _ui_window_filename = 'ui_exp_configurator.ui'

    # Signals
    sigSaveConfig = QtCore.Signal(str, str, object)
    sigLoadConfig = QtCore.Signal(str)
    sigAddEntry = QtCore.Signal(str, float, int, float, int)
    sigDeleteEntry = QtCore.Signal(QtCore.QModelIndex)

    def __init__(self, config, **kwargs):
        # load connection
        super().__init__(config=config, **kwargs)
        self._exp_logic = None
        self._mw = None

    def on_activate(self):
        """ Required initialization steps.
        """
        self._exp_logic = self.exp_logic()

        self._mw = ExpConfiguratorWindow(self._ui_window_filename)
        self._mw.formWidget.hide()

        # initialize combobox
        self._mw.select_experiment_ComboBox.addItem("Select your experiment..")
        self._mw.select_experiment_ComboBox.addItems(self._exp_logic.experiment_labels)

        # disable the save configuration toolbuttons while no experiment selected yet
        self._mw.save_config_Action.setDisabled(True)
        self._mw.save_config_copy_Action.setDisabled(True)

        # initialize the entry form
        self.init_configuration_form()

        # initialize list view
        self._mw.imaging_sequence_ListView.setModel(self._exp_logic.img_sequence_model)

        # signals
        # internal signals
        # toolbar
        self._mw.save_config_Action.triggered.connect(self.save_config_clicked)
        self._mw.save_config_copy_Action.triggered.connect(self.save_config_copy_clicked)
        self._mw.load_config_Action.triggered.connect(self.load_config_clicked)
        self._mw.clear_all_Action.triggered.connect(self.clear_all_clicked)

        # widgets on the configuration form
        # self._mw.select_experiment_ComboBox.activated[str].connect(self.update_form)
        # self._mw.select_experiment_ComboBox.activated[str].connect(self.start_new_experiment_config)
        self._mw.select_experiment_ComboBox.textActivated.connect(self.start_new_experiment_config)

        self._mw.sample_name_LineEdit.textChanged.connect(self._exp_logic.update_sample_name)
        self._mw.mail_LineEdit.textChanged.connect(self._exp_logic.update_mail_address)
        self._mw.dapi_CheckBox.stateChanged.connect(self._exp_logic.update_is_dapi)
        self._mw.rna_CheckBox.stateChanged.connect(self._exp_logic.update_is_rna)
        self._mw.TransferData_checkBox.stateChanged.connect(self._exp_logic.update_data_transfer)
        self._mw.exposure_DSpinBox.valueChanged.connect(self._exp_logic.update_exposure)
        self._mw.gain_SpinBox.valueChanged.connect(self._exp_logic.update_gain)
        self._mw.num_frames_SpinBox.valueChanged.connect(self._exp_logic.update_frames)
        self._mw.filterpos_ComboBox.currentIndexChanged.connect(self._exp_logic.update_filterpos)
        self._mw.save_path_LineEdit.textChanged.connect(self._exp_logic.update_save_path)
        self._mw.save_network_path_LineEdit.textChanged.connect(self._exp_logic.update_save_network_path)
        self._mw.fileformat_ComboBox.currentTextChanged.connect(self._exp_logic.update_fileformat)
        self._mw.num_z_planes_SpinBox.valueChanged.connect(self._exp_logic.update_num_z_planes)
        self._mw.z_step_DSpinBox.valueChanged.connect(self._exp_logic.update_z_step)
        self._mw.centered_focal_plane_CheckBox.stateChanged.connect(self._exp_logic.update_centered_focal_plane)
        self._mw.roi_list_path_LineEdit.textChanged.connect(self._exp_logic.update_roi_path)
        self._mw.injections_list_LineEdit.textChanged.connect(self._exp_logic.update_injections_path)
        self._mw.dapi_data_LineEdit.textChanged.connect(self._exp_logic.update_dapi_path)
        self._mw.reference_images_lineEdit.textChanged.connect(self._exp_logic.update_zen_ref_images_path)
        self._mw.Zen_saving_folder_lineEdit.textChanged.connect(self._exp_logic.update_zen_saving_path)
        self._mw.Zen_correlation_DSpinBox.valueChanged.connect(self._exp_logic.update_correlation_threshold)
        self._mw.illumination_time_DSpinBox.valueChanged.connect(self._exp_logic.update_illumination_time)
        self._mw.num_iterations_SpinBox.valueChanged.connect(self._exp_logic.update_num_iterations)
        self._mw.time_step_SpinBox.valueChanged.connect(self._exp_logic.update_time_step)
        self._mw.axial_calibration_path_lineEdit.textChanged.connect(self._exp_logic.update_axial_calibration_path)

        # pushbuttons
        # pushbuttons belonging to the listview
        self._mw.add_entry_PushButton.clicked.connect(self.add_entry_clicked)
        self._mw.delete_entry_PushButton.clicked.connect(self.delete_entry_clicked)
        self._mw.delete_all_PushButton.clicked.connect(self._exp_logic.delete_imaging_list)

        # get-current-value pushbutton signals (only available if instruments are connected)
        self._mw.get_exposure_PushButton.clicked.connect(self._exp_logic.get_exposure)
        self._mw.get_exposure_PushButton.setEnabled(self._exp_logic.camera_available)
        self._mw.get_gain_PushButton.clicked.connect(self._exp_logic.get_gain)
        self._mw.get_gain_PushButton.setEnabled(self._exp_logic.camera_available)
        self._mw.get_filterpos_PushButton.clicked.connect(self._exp_logic.get_filterpos)
        self._mw.get_filterpos_PushButton.setEnabled(self._exp_logic.filterwheel_available)

        # load file pushbutton signals
        self._mw.load_roi_PushButton.clicked.connect(self.load_roi_list_clicked)
        self._mw.load_injections_PushButton.clicked.connect(self.load_injections_clicked)
        self._mw.load_dapi_PushButton.clicked.connect(self.load_dapi_path_clicked)
        self._mw.reference_images_pushButton.clicked.connect(self.load_ref_images_path_clicked)
        self._mw.Zen_saving_folder_pushButton.clicked.connect(self.load_zen_saving_path_clicked)
        self._mw.load_dz_calibration_pushButton.clicked.connect(self.load_axial_calibration_path_clicked)

        # signals to logic
        self.sigSaveConfig.connect(self._exp_logic.save_to_exp_config_file)
        self.sigLoadConfig.connect(self._exp_logic.load_config_file)
        self.sigAddEntry.connect(self._exp_logic.add_entry_to_imaging_list)
        self.sigDeleteEntry.connect(self._exp_logic.delete_entry_from_imaging_list)

        # signals from logic
        self._exp_logic.sigConfigDictUpdated.connect(self.update_entries)
        self._exp_logic.sigImagingListChanged.connect(self.update_listview)
        self._exp_logic.sigConfigLoaded.connect(self.display_loaded_config)
        self._exp_logic.sigUpdateListModel.connect(self.update_list_model)

    def on_deactivate(self):
        """ Deinitialisation performed during deactivation of the module.
        """
        self._mw.close()

    def show(self):
        """Make window visible and put it above all other windows.
        """
        QtWidgets.QMainWindow.show(self._mw)
        self._mw.activateWindow()
        self._mw.raise_()

    def init_configuration_form(self):
        """Populate setup-dependent combo boxes."""
        self._mw.filterpos_ComboBox.addItems(list(self._exp_logic.filters or []))
        self._mw.laser_ComboBox.addItems(list(self._exp_logic.lasers or []))
        self._mw.fileformat_ComboBox.addItems(list(self._exp_logic.supported_fileformats or []))

# ----------------------------------------------------------------------------------------------------------------------
# General private methods to hide or reset widgets
# ----------------------------------------------------------------------------------------------------------------------
    def _set_named_widgets_visible(self, widget_names, visible: bool) -> None:
        """Show or hide widgets identified by names in the UI file."""
        for widget_name in widget_names:
            widget = getattr(self._mw, widget_name, None)

            if widget is None:
                self.log.warning(f"Widget {widget_name!r} is not available in the UI.")
                continue

            widget.setVisible(bool(visible))

    def _hide_experiment_form(self) -> None:
        """Hide all configurable sections and fields."""
        for method_name in self.SECTION_VISIBILITY_METHODS.values():
            visibility_method = getattr(self, method_name)
            visibility_method(False)

        for widget_names in self.FIELD_WIDGETS.values():
            self._set_named_widgets_visible(widget_names,False,)

        self._mw.formWidget.hide()
        self._mw.save_config_Action.setDisabled(True)
        self._mw.save_config_copy_Action.setDisabled(True)

# ----------------------------------------------------------------------------------------------------------------------
# Methods to adapt the configuration form depending on the current experiment
# ----------------------------------------------------------------------------------------------------------------------

    def apply_experiment_definition(self, definition: dict) -> None:
        """Configure the form from an experiment-definition dictionary.

        Args:
            definition: Parsed YAML experiment definition.
        """
        if not isinstance(definition, dict):
            raise TypeError("Experiment definition must be a dictionary.")

        experiment = definition.get("experiment")

        if not experiment:
            raise ValueError("Experiment definition has no 'experiment' entry.")

        fields = definition.get("fields", {})

        if not isinstance(fields, dict):
            raise TypeError(f"The 'fields' entry for {experiment!r} must be a dictionary.")

        # Begin from a completely hidden form so that parameters
        # from the previously selected experiment do not remain visible.
        self._hide_experiment_form()
        visible_fields = []

        for field_name, field_definition in fields.items():
            if field_definition is None:
                field_definition = {}

            if not isinstance(field_definition, dict):
                raise TypeError(f"Definition of field {field_name!r} must be a dictionary.")

            # A field is visible by default simply by being present.
            if field_definition.get("visible", True):
                visible_fields.append(field_name)

        # Determine which form sections are required.
        visible_sections = set()

        for field_name in visible_fields:
            section_name = self.FIELD_SECTIONS.get(field_name)

            if section_name is None:
                self.log.warning(f"No GUI section is registered for field {field_name!r}.")
                continue

            visible_sections.add(section_name)

        # Optional explicit sections may be added to the YAML later.
        configured_sections = definition.get("sections")

        if isinstance(configured_sections, list):
            visible_sections.update(str(section) for section in configured_sections)

        elif isinstance(configured_sections, dict):
            visible_sections.update(str(section) for section, visible in configured_sections.items() if visible)

        # Show the required section containers.
        for section_name in visible_sections:
            method_name = self.SECTION_VISIBILITY_METHODS.get(section_name)

            if method_name is None:
                self.log.warning(f"Unknown GUI section {section_name!r} in experiment {experiment!r}.")
                continue

            visibility_method = getattr(self, method_name)
            visibility_method(True)

        # Section helpers currently show all widgets belonging to a
        # section. Hide the individual fields again, then selectively
        # show only the fields declared by the YAML definition.
        for widget_names in self.FIELD_WIDGETS.values():
            self._set_named_widgets_visible(widget_names,False,)

        for field_name in visible_fields:
            widget_names = self.FIELD_WIDGETS.get(field_name)

            if widget_names is None:
                self.log.warning(f"Unknown experiment field {field_name!r}. No widgets are registered for this field.")
                continue

            self._set_named_widgets_visible(widget_names,True)

        self._apply_imaging_sequence_definition(fields)
        description = str(definition.get("description", "")).strip()

        self._mw.select_experiment_ComboBox.setToolTip(description)

        if self._mw.statusBar() is not None:
            self._mw.statusBar().showMessage(description)

        # This can be used later if a dedicated label is added
        # with Qt Designer.
        description_label = getattr(self._mw, "experiment_description_Label", None)

        if description_label is not None:
            description_label.setText(description)
            description_label.setVisible(bool(description))

        self._mw.formWidget.setVisible(bool(visible_fields))
        self._mw.save_config_Action.setDisabled(False)
        self._mw.save_config_copy_Action.setDisabled(False)

    def _apply_imaging_sequence_definition(self, fields: dict) -> None:
        """Configure the imaging-sequence editor."""
        imaging_definition = fields.get("imaging_sequence", {})

        if imaging_definition is None:
            imaging_definition = {}

        self._exp_logic.is_timelapse_ramm = False
        self._exp_logic.is_timelapse_palm = False
        self._mw.imaging_sequence_ListView.setModel(self._exp_logic.img_sequence_model)

        self._mw.laser_ComboBox.clear()
        self._mw.laser_ComboBox.addItems(list(self._exp_logic.lasers or []))

        if "imaging_sequence" not in fields:
            return

        model_name = imaging_definition.get("model", "standard")
        if model_name == "timelapse_ramm":
            self._exp_logic.is_timelapse_ramm = True
            self._mw.imaging_sequence_ListView.setModel(self._exp_logic.img_sequence_model_timelapse_ramm)

        elif model_name == "timelapse_palm":
            self._exp_logic.is_timelapse_palm = True
            self._mw.imaging_sequence_ListView.setModel(self._exp_logic.img_sequence_model_timelapse_palm)

        elif model_name != "standard":
            raise ValueError(f"Unknown imaging-sequence model {model_name!r}.")

        additional_sources = imaging_definition.get("additional_sources", [])
        self._mw.laser_ComboBox.addItems([str(source) for source in additional_sources])

    @QtCore.Slot(str)
    def start_new_experiment_config(self, experiment: str) -> None:
        """Initialize the GUI for the selected experiment."""

        if experiment == "Select your experiment..":
            self._hide_experiment_form()
            return

        try:
            definition = (self._exp_logic.experiment_definitions[experiment])
        except KeyError:
            self.log.error(f"No definition is available for experiment {experiment!r}.")
            self._hide_experiment_form()
            return

        try:
            self._exp_logic.init_config_from_definition(experiment)
            self.apply_experiment_definition(definition)
            self.update_entries()

        except Exception:
            self.log.exception(f"Could not initialize experiment {experiment!r}.")
            self._hide_experiment_form()

    # def update_form(self):
    #     """ Update the configuration form according to the selected experiment type.
    #     Sets the visibility of the GUI widgets depending on whether an information is required for the selected
    #     experiment type or not.
    #
    #     When implementing new experiments, an additional case must be defined here.
    #     """
    #     experiment = self._mw.select_experiment_ComboBox.currentText()
    #     self._mw.save_config_Action.setDisabled(False)
    #     self._mw.save_config_copy_Action.setDisabled(False)
    #     self._mw.laser_ComboBox.clear()  # reset content of laser selection to default state because it could have been modified (see 'Photobleaching' experiment)
    #     self._mw.laser_ComboBox.addItems(self._exp_logic.lasers)
    #
    #     if experiment == 'Select your experiment..':
    #         self._mw.formWidget.hide()
    #         self._mw.save_config_Action.setDisabled(True)
    #         self._mw.save_config_copy_Action.setDisabled(True)
    #
    #     elif experiment == 'Multicolor imaging PALM':
    #         # chose the right the listview model
    #         self._mw.imaging_sequence_ListView.setModel(self._exp_logic.img_sequence_model)
    #         self._exp_logic.is_timelapse_ramm = False
    #         self._exp_logic.is_timelapse_palm = False
    #
    #         self._mw.formWidget.setVisible(True)
    #         self.set_visibility_general_settings(True)
    #         self.set_visibility_camera_settings(True)
    #         self.set_visibility_filter_settings(True)
    #         self.set_visibility_imaging_settings(True)
    #         self.set_visibility_save_settings(True)
    #         self.set_visibility_scan_settings(False)
    #         self.set_visibility_documents_settings(False)
    #         self.set_visibility_prebleaching_settings(False)
    #         self.set_visibility_timelapse_settings(False)
    #         self.set_visibility_ZEN_security_settings(False)
    #
    #         # additional visibility settings
    #         self._mw.save_remote_path_Label.setVisible(False)
    #         self._mw.save_network_path_LineEdit.setVisible(False)
    #         self._mw.TransferData_checkBox.setVisible(False)
    #
    #     elif experiment == 'Multicolor scan PALM':
    #         # chose the right the listview model
    #         self._mw.imaging_sequence_ListView.setModel(self._exp_logic.img_sequence_model)
    #         self._exp_logic.is_timelapse_ramm = False
    #         self._exp_logic.is_timelapse_palm = False
    #
    #         self._mw.formWidget.setVisible(True)
    #         self.set_visibility_general_settings(True)
    #         self.set_visibility_camera_settings(True)
    #         self.set_visibility_filter_settings(True)
    #         self.set_visibility_imaging_settings(True)
    #         self.set_visibility_save_settings(True)
    #         self.set_visibility_scan_settings(True)
    #         self.set_visibility_documents_settings(False)
    #         self.set_visibility_prebleaching_settings(False)
    #         self.set_visibility_timelapse_settings(False)
    #         self.set_visibility_ZEN_security_settings(False)
    #
    #         # additional visibility settings
    #         self._mw.save_remote_path_Label.setVisible(False)
    #         self._mw.save_network_path_LineEdit.setVisible(False)
    #         self._mw.TransferData_checkBox.setVisible(False)
    #
    #     elif experiment == 'Multicolor scan RAMM':
    #         # chose the right the listview model
    #         self._mw.imaging_sequence_ListView.setModel(self._exp_logic.img_sequence_model)
    #         self._exp_logic.is_timelapse_ramm = False
    #         self._exp_logic.is_timelapse_palm = False
    #
    #         self._mw.formWidget.setVisible(True)
    #         self.set_visibility_general_settings(True)
    #         self.set_visibility_camera_settings(True)
    #         self.set_visibility_filter_settings(False)
    #         self.set_visibility_imaging_settings(True)
    #         self.set_visibility_save_settings(True)
    #         self.set_visibility_scan_settings(True)
    #         self.set_visibility_documents_settings(False)
    #         self.set_visibility_prebleaching_settings(False)
    #         self.set_visibility_timelapse_settings(False)
    #         self.set_visibility_ZEN_security_settings(False)
    #
    #         # additional visibility settings
    #         self._mw.gain_Label.setVisible(False)
    #         self._mw.gain_SpinBox.setVisible(False)
    #         self._mw.get_gain_PushButton.setVisible(False)
    #         self._mw.num_frames_Label.setVisible(False)
    #         self._mw.num_frames_SpinBox.setVisible(False)
    #         self._mw.save_remote_path_Label.setVisible(False)
    #         self._mw.save_network_path_LineEdit.setVisible(False)
    #         self._mw.TransferData_checkBox.setVisible(False)
    #
    #         # Modify the laser list in order to add the bright field control
    #         self._mw.laser_ComboBox.addItems(['Brightfield'])
    #
    #     elif experiment == 'PAINT RAMM':
    #         # chose the right the listview model
    #         self._mw.imaging_sequence_ListView.setModel(self._exp_logic.img_sequence_model)
    #         self._exp_logic.is_timelapse_ramm = False
    #         self._exp_logic.is_timelapse_palm = False
    #
    #         self._mw.formWidget.setVisible(True)
    #         self.set_visibility_general_settings(True)
    #         self.set_visibility_camera_settings(True)
    #         self.set_visibility_filter_settings(False)
    #         self.set_visibility_imaging_settings(True)
    #         self.set_visibility_save_settings(True)
    #         self.set_visibility_scan_settings(True)
    #         self.set_visibility_documents_settings(False)
    #         self.set_visibility_prebleaching_settings(False)
    #         self.set_visibility_timelapse_settings(False)
    #         self.set_visibility_ZEN_security_settings(False)
    #
    #         # additional visibility settings
    #         self._mw.gain_Label.setVisible(False)
    #         self._mw.gain_SpinBox.setVisible(False)
    #         self._mw.get_gain_PushButton.setVisible(False)
    #         self._mw.num_frames_Label.setVisible(False)
    #         self._mw.num_frames_SpinBox.setVisible(False)
    #         self._mw.save_remote_path_Label.setVisible(False)
    #         self._mw.save_network_path_LineEdit.setVisible(False)
    #         self._mw.TransferData_checkBox.setVisible(False)
    #         self._mw.z_step_Label.setVisible(False)
    #         self._mw.z_step_DSpinBox.setVisible(False)
    #         self._mw.centered_focal_plane_CheckBox.setVisible(False)
    #         self._mw.fileformat_ComboBox.setVisible(False)
    #         self._mw.fileformat_Label.setVisible(False)
    #         self._mw.num_z_planes_Label.setText('Total number of images to acquire')
    #         self._mw.scan_settings_Label.setText('Acquisition pipeline')
    #
    #         # Modify the laser list in order to add the bright field control
    #         self._mw.laser_ComboBox.addItems(['Brightfield'])
    #
    #     elif experiment == 'Multicolor scan Airyscan':
    #         # chose the right the listview model
    #         self._mw.imaging_sequence_ListView.setModel(self._exp_logic.img_sequence_model)
    #         self._exp_logic.is_timelapse_ramm = False
    #         self._exp_logic.is_timelapse_palm = False
    #
    #         self._mw.formWidget.setVisible(True)
    #         self.set_visibility_general_settings(False)
    #         self.set_visibility_camera_settings(False)
    #         self.set_visibility_filter_settings(False)
    #         self.set_visibility_imaging_settings(True)
    #         self.set_visibility_save_settings(False)
    #         self.set_visibility_scan_settings(True)
    #         self.set_visibility_documents_settings(False)
    #         self.set_visibility_prebleaching_settings(False)
    #         self.set_visibility_timelapse_settings(False)
    #         self.set_visibility_ZEN_security_settings(False)
    #
    #         # additional visibility settings
    #         self._mw.gain_Label.setVisible(False)
    #         self._mw.gain_SpinBox.setVisible(False)
    #         self._mw.get_gain_PushButton.setVisible(False)
    #         self._mw.num_frames_Label.setVisible(False)
    #         self._mw.num_frames_SpinBox.setVisible(False)
    #         self._mw.save_remote_path_Label.setVisible(False)
    #         self._mw.save_network_path_LineEdit.setVisible(False)
    #         self._mw.TransferData_checkBox.setVisible(False)
    #
    #     elif experiment == 'ROI multicolor scan PALM':
    #         # chose the right the listview model
    #         self._mw.imaging_sequence_ListView.setModel(self._exp_logic.img_sequence_model)
    #         self._exp_logic.is_timelapse_ramm = False
    #         self._exp_logic.is_timelapse_palm = False
    #
    #         self._mw.formWidget.setVisible(True)
    #         self.set_visibility_general_settings(True)
    #         self.set_visibility_camera_settings(True)
    #         self.set_visibility_filter_settings(True)
    #         self.set_visibility_imaging_settings(True)
    #         self.set_visibility_save_settings(True)
    #         self.set_visibility_scan_settings(True)
    #         self.set_visibility_documents_settings(True)
    #         self.set_visibility_prebleaching_settings(False)
    #         self.set_visibility_timelapse_settings(False)
    #         self.set_visibility_ZEN_security_settings(False)
    #
    #         # additional visibility modifications
    #         self._mw.injections_list_Label.setVisible(False)
    #         self._mw.injections_list_LineEdit.setVisible(False)
    #         self._mw.load_injections_PushButton.setVisible(False)
    #         self._mw.dapi_path_Label.setVisible(False)
    #         self._mw.dapi_data_LineEdit.setVisible(False)
    #         self._mw.load_dapi_PushButton.setVisible(False)
    #         self._mw.save_remote_path_Label.setVisible(False)
    #         self._mw.save_network_path_LineEdit.setVisible(False)
    #         self._mw.TransferData_checkBox.setVisible(False)
    #
    #     elif experiment == 'ROI multicolor scan RAMM':
    #         # chose the right the listview model
    #         self._mw.imaging_sequence_ListView.setModel(self._exp_logic.img_sequence_model)
    #         self._exp_logic.is_timelapse_ramm = False
    #         self._exp_logic.is_timelapse_palm = False
    #
    #         self._mw.formWidget.setVisible(True)
    #         self.set_visibility_general_settings(True)
    #         self.set_visibility_camera_settings(True)
    #         self.set_visibility_filter_settings(False)
    #         self.set_visibility_imaging_settings(True)
    #         self.set_visibility_save_settings(True)
    #         self.set_visibility_scan_settings(True)
    #         self.set_visibility_documents_settings(True)
    #         self.set_visibility_prebleaching_settings(False)
    #         self.set_visibility_timelapse_settings(False)
    #         self.set_visibility_ZEN_security_settings(False)
    #
    #         # additional visibility modifications
    #         self._mw.dapi_CheckBox.setVisible(True)
    #         self._mw.rna_CheckBox.setVisible(True)
    #         self._mw.gain_Label.setVisible(False)
    #         self._mw.gain_SpinBox.setVisible(False)
    #         self._mw.get_gain_PushButton.setVisible(False)
    #         self._mw.injections_list_Label.setVisible(False)
    #         self._mw.injections_list_LineEdit.setVisible(False)
    #         self._mw.load_injections_PushButton.setVisible(False)
    #         self._mw.dapi_path_Label.setVisible(False)
    #         self._mw.dapi_data_LineEdit.setVisible(False)
    #         self._mw.load_dapi_PushButton.setVisible(False)
    #         self._mw.num_frames_Label.setVisible(False)
    #         self._mw.num_frames_SpinBox.setVisible(False)
    #         self._mw.save_remote_path_Label.setVisible(False)
    #         self._mw.save_network_path_LineEdit.setVisible(False)
    #         self._mw.TransferData_checkBox.setVisible(False)
    #
    #         # Modify the laser list in order to add the bright field control
    #         self._mw.laser_ComboBox.addItems(['Brightfield'])
    #
    #     elif experiment == 'ROI multicolor scan Airyscan':
    #         # chose the right the listview model
    #         self._mw.imaging_sequence_ListView.setModel(self._exp_logic.img_sequence_model)
    #         self._exp_logic.is_timelapse_ramm = False
    #         self._exp_logic.is_timelapse_palm = False
    #
    #         self._mw.formWidget.setVisible(True)
    #         self.set_visibility_general_settings(True)
    #         self.set_visibility_camera_settings(False)
    #         self.set_visibility_filter_settings(False)
    #         self.set_visibility_imaging_settings(True)
    #         self.set_visibility_save_settings(True)
    #         self.set_visibility_scan_settings(True)
    #         self.set_visibility_documents_settings(True)
    #         self.set_visibility_prebleaching_settings(False)
    #         self.set_visibility_timelapse_settings(False)
    #         self.set_visibility_ZEN_security_settings(False)
    #
    #         # additional visibility modifications
    #         self._mw.dapi_CheckBox.setVisible(True)
    #         self._mw.rna_CheckBox.setVisible(True)
    #         self._mw.gain_Label.setVisible(False)
    #         self._mw.gain_SpinBox.setVisible(False)
    #         self._mw.get_gain_PushButton.setVisible(False)
    #         self._mw.injections_list_Label.setVisible(False)
    #         self._mw.injections_list_LineEdit.setVisible(False)
    #         self._mw.load_injections_PushButton.setVisible(False)
    #         self._mw.dapi_path_Label.setVisible(False)
    #         self._mw.dapi_data_LineEdit.setVisible(False)
    #         self._mw.load_dapi_PushButton.setVisible(False)
    #         self._mw.num_frames_Label.setVisible(False)
    #         self._mw.num_frames_SpinBox.setVisible(False)
    #         self._mw.save_remote_path_Label.setVisible(False)
    #         self._mw.save_network_path_LineEdit.setVisible(False)
    #         self._mw.TransferData_checkBox.setVisible(False)
    #         self._mw.z_step_Label.setVisible(False)
    #         self._mw.z_step_DSpinBox.setVisible(False)
    #         self._mw.centered_focal_plane_CheckBox.setVisible(False)
    #
    #     elif experiment == 'ROI multicolor scan Airyscan confocal':
    #         # chose the right the listview model
    #         # self._mw.imaging_sequence_ListView.setModel(self._exp_logic.img_sequence_model)
    #         self._exp_logic.is_timelapse_ramm = False
    #         self._exp_logic.is_timelapse_palm = False
    #
    #         self._mw.formWidget.setVisible(True)
    #         self.set_visibility_general_settings(True)
    #         self.set_visibility_camera_settings(False)
    #         self.set_visibility_filter_settings(False)
    #         self.set_visibility_imaging_settings(False)
    #         self.set_visibility_save_settings(True)
    #         self.set_visibility_scan_settings(False)
    #         self.set_visibility_documents_settings(True)
    #         self.set_visibility_prebleaching_settings(False)
    #         self.set_visibility_timelapse_settings(False)
    #         self.set_visibility_ZEN_security_settings(False)
    #
    #         # additional visibility modifications
    #         self._mw.dapi_CheckBox.setVisible(False)
    #         self._mw.rna_CheckBox.setVisible(False)
    #         self._mw.gain_Label.setVisible(False)
    #         self._mw.gain_SpinBox.setVisible(False)
    #         self._mw.get_gain_PushButton.setVisible(False)
    #         self._mw.injections_list_Label.setVisible(False)
    #         self._mw.injections_list_LineEdit.setVisible(False)
    #         self._mw.load_injections_PushButton.setVisible(False)
    #         self._mw.dapi_path_Label.setVisible(False)
    #         self._mw.dapi_data_LineEdit.setVisible(False)
    #         self._mw.load_dapi_PushButton.setVisible(False)
    #         self._mw.num_frames_Label.setVisible(False)
    #         self._mw.num_frames_SpinBox.setVisible(False)
    #         self._mw.save_remote_path_Label.setVisible(False)
    #         self._mw.save_network_path_LineEdit.setVisible(False)
    #         self._mw.TransferData_checkBox.setVisible(False)
    #         self._mw.fileformat_Label.setVisible(False)
    #         self._mw.fileformat_ComboBox.setVisible(False)
    #         self._mw.z_step_Label.setVisible(False)
    #         self._mw.z_step_DSpinBox.setVisible(False)
    #         self._mw.centered_focal_plane_CheckBox.setVisible(False)
    #
    #     elif experiment == 'Fluidics RAMM' or experiment == 'Fluidics Airyscan':
    #         # chose the right the listview model
    #         self._mw.imaging_sequence_ListView.setModel(self._exp_logic.img_sequence_model)
    #         self._exp_logic.is_timelapse_ramm = False
    #         self._exp_logic.is_timelapse_palm = False
    #
    #         self._mw.formWidget.setVisible(True)
    #         self.set_visibility_general_settings(False)
    #         self.set_visibility_camera_settings(False)
    #         self.set_visibility_filter_settings(False)
    #         self.set_visibility_imaging_settings(False)
    #         self.set_visibility_save_settings(False)
    #         self.set_visibility_scan_settings(False)
    #         self.set_visibility_documents_settings(True)
    #         self.set_visibility_prebleaching_settings(False)
    #         self.set_visibility_timelapse_settings(False)
    #         self.set_visibility_ZEN_security_settings(False)
    #
    #         # additional visibility modifications
    #         self._mw.roi_list_path_Label.setVisible(False)
    #         self._mw.roi_list_path_LineEdit.setVisible(False)
    #         self._mw.load_roi_PushButton.setVisible(False)
    #         self._mw.dapi_path_Label.setVisible(False)
    #         self._mw.dapi_data_LineEdit.setVisible(False)
    #         self._mw.load_dapi_PushButton.setVisible(False)
    #
    #     elif experiment == 'Hi-M RAMM':
    #         # chose the right the listview model
    #         self._mw.imaging_sequence_ListView.setModel(self._exp_logic.img_sequence_model)
    #         self._exp_logic.is_timelapse_ramm = False
    #         self._exp_logic.is_timelapse_palm = False
    #
    #         self._mw.formWidget.setVisible(True)
    #         self.set_visibility_general_settings(True)
    #         self.set_visibility_camera_settings(True)
    #         self.set_visibility_filter_settings(False)
    #         self.set_visibility_imaging_settings(True)
    #         self.set_visibility_save_settings(True)
    #         self.set_visibility_scan_settings(True)
    #         self.set_visibility_documents_settings(True)
    #         self.set_visibility_prebleaching_settings(False)
    #         self.set_visibility_timelapse_settings(False)
    #         self.set_visibility_ZEN_security_settings(False)
    #
    #         # additional visibility settings
    #         self._mw.gain_Label.setVisible(False)
    #         self._mw.gain_SpinBox.setVisible(False)
    #         self._mw.get_gain_PushButton.setVisible(False)
    #         self._mw.num_frames_Label.setVisible(False)
    #         self._mw.num_frames_SpinBox.setVisible(False)
    #         self._mw.mail_LineEdit.setVisible(True)
    #         self._mw.mail_Label.setVisible(True)
    #
    #     elif experiment == 'Hi-M Autofocus Check Epi':
    #         # chose the right the listview model
    #         self._mw.imaging_sequence_ListView.setModel(self._exp_logic.img_sequence_model)
    #         self._exp_logic.is_timelapse_ramm = False
    #         self._exp_logic.is_timelapse_palm = False
    #
    #         self._mw.formWidget.setVisible(True)
    #         self.set_visibility_general_settings(True)
    #         self.set_visibility_camera_settings(False)
    #         self.set_visibility_filter_settings(False)
    #         self.set_visibility_imaging_settings(False)
    #         self.set_visibility_save_settings(True)
    #         self.set_visibility_scan_settings(False)
    #         self.set_visibility_documents_settings(True)
    #         self.set_visibility_prebleaching_settings(False)
    #         self.set_visibility_timelapse_settings(False)
    #         self.set_visibility_ZEN_security_settings(True)
    #
    #         # additional visibility settings
    #         self._mw.gain_Label.setVisible(False)
    #         self._mw.gain_SpinBox.setVisible(False)
    #         self._mw.get_gain_PushButton.setVisible(False)
    #         self._mw.num_frames_Label.setVisible(False)
    #         self._mw.num_frames_SpinBox.setVisible(False)
    #         self._mw.z_step_Label.setVisible(False)
    #         self._mw.z_step_DSpinBox.setVisible(False)
    #         self._mw.centered_focal_plane_CheckBox.setVisible(False)
    #         self._mw.save_path_Label.setVisible(False)
    #         self._mw.save_path_LineEdit.setVisible(False)
    #         self._mw.z_step_Label.setVisible(False)
    #         self._mw.z_step_DSpinBox.setVisible(False)
    #         self._mw.centered_focal_plane_CheckBox.setVisible(False)
    #         self._mw.Correlation_threshold_Label.setVisible(False)
    #         self._mw.injections_list_Label.setVisible(False)
    #         self._mw.injections_list_LineEdit.setVisible(False)
    #         self._mw.save_remote_path_Label.setVisible(False)
    #         self._mw.save_network_path_LineEdit.setVisible(False)
    #         self._mw.TransferData_checkBox.setVisible(False)
    #         self._mw.load_injections_PushButton.setVisible(False)
    #         self._mw.Zen_correlation_DSpinBox.setVisible(False)
    #
    #         self._mw.mail_LineEdit.setVisible(False)
    #         self._mw.mail_Label.setVisible(False)
    #         self._mw.Zen_saving_folder_Label.setVisible(True)
    #         self._mw.Zen_saving_folder_lineEdit.setVisible(True)
    #         self._mw.Zen_saving_folder_pushButton.setVisible(True)
    #
    #     elif experiment == 'Hi-M Airyscan Epi':
    #         # chose the right the listview model
    #         self._mw.imaging_sequence_ListView.setModel(self._exp_logic.img_sequence_model)
    #         self._exp_logic.is_timelapse_ramm = False
    #         self._exp_logic.is_timelapse_palm = False
    #
    #         self._mw.formWidget.setVisible(True)
    #         self.set_visibility_general_settings(True)
    #         self.set_visibility_camera_settings(False)
    #         self.set_visibility_filter_settings(False)
    #         self.set_visibility_imaging_settings(True)
    #         self.set_visibility_save_settings(True)
    #         self.set_visibility_scan_settings(True)
    #         self.set_visibility_documents_settings(True)
    #         self.set_visibility_prebleaching_settings(False)
    #         self.set_visibility_timelapse_settings(False)
    #         self.set_visibility_ZEN_security_settings(True)
    #
    #         # additional visibility settings
    #         self._mw.gain_Label.setVisible(False)
    #         self._mw.gain_SpinBox.setVisible(False)
    #         self._mw.get_gain_PushButton.setVisible(False)
    #         self._mw.num_frames_Label.setVisible(False)
    #         self._mw.num_frames_SpinBox.setVisible(False)
    #         self._mw.z_step_Label.setVisible(False)
    #         self._mw.z_step_DSpinBox.setVisible(False)
    #         self._mw.centered_focal_plane_CheckBox.setVisible(False)
    #         self._mw.save_path_Label.setVisible(False)
    #         self._mw.save_path_LineEdit.setVisible(False)
    #
    #         self._mw.mail_LineEdit.setVisible(True)
    #         self._mw.mail_Label.setVisible(True)
    #         self._mw.Zen_saving_folder_Label.setVisible(True)
    #         self._mw.Zen_saving_folder_lineEdit.setVisible(True)
    #         self._mw.Zen_saving_folder_pushButton.setVisible(True)
    #
    #     # elif experiment == 'Hi-M Airyscan Lumencor':
    #     #     # chose the right the listview model
    #     #     self._mw.imaging_sequence_ListView.setModel(self._exp_logic.img_sequence_model)
    #     #     self._exp_logic.is_timelapse_ramm = False
    #     #     self._exp_logic.is_timelapse_palm = False
    #     #
    #     #     self._mw.formWidget.setVisible(True)
    #     #     self.set_visibility_general_settings(True)
    #     #     self.set_visibility_camera_settings(False)
    #     #     self.set_visibility_filter_settings(False)
    #     #     self.set_visibility_imaging_settings(True)
    #     #     self.set_visibility_save_settings(True)
    #     #     self.set_visibility_scan_settings(True)
    #     #     self.set_visibility_documents_settings(True)
    #     #     self.set_visibility_prebleaching_settings(False)
    #     #     self.set_visibility_timelapse_settings(False)
    #     #     self.set_visibility_ZEN_security_settings(False)
    #     #
    #     #     # additional visibility settings
    #     #     self._mw.gain_Label.setVisible(False)
    #     #     self._mw.gain_SpinBox.setVisible(False)
    #     #     self._mw.get_gain_PushButton.setVisible(False)
    #     #     self._mw.num_frames_Label.setVisible(False)
    #     #     self._mw.num_frames_SpinBox.setVisible(False)
    #     #     self._mw.save_remote_path_Label.setVisible(False)
    #     #     self._mw.save_network_path_LineEdit.setVisible(False)
    #     #     self._mw.TransferData_checkBox.setVisible(False)
    #     #     self._mw.z_step_Label.setVisible(False)
    #     #     self._mw.z_step_DSpinBox.setVisible(False)
    #     #     self._mw.centered_focal_plane_CheckBox.setVisible(False)
    #     #     self._mw.mail_LineEdit.setVisible(True)
    #     #     self._mw.mail_Label.setVisible(True)
    #
    #     elif experiment == 'Hi-M Airyscan Confocal':
    #         # chose the right the listview model
    #         self._mw.imaging_sequence_ListView.setModel(self._exp_logic.img_sequence_model)
    #         self._exp_logic.is_timelapse_ramm = False
    #         self._exp_logic.is_timelapse_palm = False
    #
    #         self._mw.formWidget.setVisible(True)
    #         self.set_visibility_general_settings(True)
    #         self.set_visibility_camera_settings(False)
    #         self.set_visibility_filter_settings(False)
    #         self.set_visibility_imaging_settings(False)
    #         self.set_visibility_save_settings(True)
    #         self.set_visibility_scan_settings(False)
    #         self.set_visibility_documents_settings(True)
    #         self.set_visibility_prebleaching_settings(False)
    #         self.set_visibility_timelapse_settings(False)
    #         self.set_visibility_ZEN_security_settings(False)
    #
    #         # additional visibility settings
    #         self._mw.gain_Label.setVisible(False)
    #         self._mw.gain_SpinBox.setVisible(False)
    #         self._mw.get_gain_PushButton.setVisible(False)
    #         self._mw.num_frames_Label.setVisible(False)
    #         self._mw.num_frames_SpinBox.setVisible(False)
    #         self._mw.save_remote_path_Label.setVisible(False)
    #         self._mw.save_network_path_LineEdit.setVisible(False)
    #         self._mw.TransferData_checkBox.setVisible(False)
    #         self._mw.z_step_Label.setVisible(False)
    #         self._mw.z_step_DSpinBox.setVisible(False)
    #         self._mw.centered_focal_plane_CheckBox.setVisible(False)
    #         self._mw.mail_LineEdit.setVisible(True)
    #         self._mw.mail_Label.setVisible(True)
    #
    #     elif experiment == 'Photobleaching RAMM' or experiment == 'Photobleaching Airyscan':
    #         # chose the right the listview model
    #         self._mw.imaging_sequence_ListView.setModel(self._exp_logic.img_sequence_model)
    #         self._exp_logic.is_timelapse_ramm = False
    #         self._exp_logic.is_timelapse_palm = False
    #
    #         self._mw.formWidget.setVisible(True)
    #         self.set_visibility_general_settings(False)
    #         self.set_visibility_camera_settings(False)
    #         self.set_visibility_filter_settings(False)
    #         self.set_visibility_imaging_settings(True)
    #         self.set_visibility_save_settings(False)
    #         self.set_visibility_scan_settings(False)
    #         self.set_visibility_documents_settings(True)
    #         self.set_visibility_prebleaching_settings(True)
    #         self.set_visibility_timelapse_settings(False)
    #         self.set_visibility_ZEN_security_settings(False)
    #
    #         # additional visibility modifications
    #         self._mw.injections_list_Label.setVisible(False)
    #         self._mw.injections_list_LineEdit.setVisible(False)
    #         self._mw.load_injections_PushButton.setVisible(False)
    #         self._mw.dapi_path_Label.setVisible(False)
    #         self._mw.dapi_data_LineEdit.setVisible(False)
    #         self._mw.load_dapi_PushButton.setVisible(False)
    #         self._mw.laser_ComboBox.removeItem(0)  # do not allow the UV laser (405 nm typically)
    #
    #     elif experiment == 'Fast timelapse RAMM' :
    #         # chose the right the listview model
    #         self._mw.imaging_sequence_ListView.setModel(self._exp_logic.img_sequence_model)
    #         self._exp_logic.is_timelapse_ramm = False  # only for 'usual' timelapse is this flag set to True
    #         self._exp_logic.is_timelapse_palm = False
    #
    #         self._mw.formWidget.setVisible(True)
    #         self.set_visibility_general_settings(True)
    #         self.set_visibility_camera_settings(True)
    #         self.set_visibility_filter_settings(False)
    #         self.set_visibility_imaging_settings(True)
    #         self.set_visibility_save_settings(True)
    #         self.set_visibility_scan_settings(True)
    #         self.set_visibility_documents_settings(True)
    #         self.set_visibility_prebleaching_settings(False)
    #         self.set_visibility_timelapse_settings(True)
    #         self.set_visibility_ZEN_security_settings(False)
    #
    #         # additional visibility modifications
    #         self._mw.gain_Label.setVisible(False)
    #         self._mw.gain_SpinBox.setVisible(False)
    #         self._mw.get_gain_PushButton.setVisible(False)
    #         self._mw.num_frames_Label.setVisible(False)
    #         self._mw.num_frames_SpinBox.setVisible(False)
    #         self._mw.injections_list_Label.setVisible(False)
    #         self._mw.injections_list_LineEdit.setVisible(False)
    #         self._mw.load_injections_PushButton.setVisible(False)
    #         self._mw.dapi_path_Label.setVisible(False)
    #         self._mw.dapi_data_LineEdit.setVisible(False)
    #         self._mw.load_dapi_PushButton.setVisible(False)
    #         self._mw.time_step_Label.setVisible(False)
    #         self._mw.time_step_SpinBox.setVisible(False)
    #         self._mw.save_remote_path_Label.setVisible(False)
    #         self._mw.save_network_path_LineEdit.setVisible(False)
    #         self._mw.TransferData_checkBox.setVisible(False)
    #
    #         # Modify the laser list in order to add the bright field control
    #         self._mw.laser_ComboBox.addItems(['Brightfield'])
    #
    #     elif experiment == 'Hubble RAMM':
    #         # chose the right the listview model
    #         self._mw.imaging_sequence_ListView.setModel(self._exp_logic.img_sequence_model)
    #         self._exp_logic.is_timelapse_ramm = False  # only for 'usual' timelapse is this flag set to True
    #         self._exp_logic.is_timelapse_palm = False
    #
    #         self._mw.formWidget.setVisible(True)
    #         self.set_visibility_general_settings(True)
    #         self.set_visibility_camera_settings(True)
    #         self.set_visibility_filter_settings(False)
    #         self.set_visibility_imaging_settings(True)
    #         self.set_visibility_save_settings(True)
    #         self.set_visibility_scan_settings(True)
    #         self.set_visibility_documents_settings(True)
    #         self.set_visibility_prebleaching_settings(False)
    #         self.set_visibility_timelapse_settings(True)
    #         self.set_visibility_ZEN_security_settings(False)
    #
    #         # additional visibility modifications
    #         self._mw.gain_Label.setVisible(False)
    #         self._mw.gain_SpinBox.setVisible(False)
    #         self._mw.get_gain_PushButton.setVisible(False)
    #         self._mw.num_frames_Label.setVisible(False)
    #         self._mw.num_frames_SpinBox.setVisible(False)
    #         self._mw.injections_list_Label.setVisible(False)
    #         self._mw.injections_list_LineEdit.setVisible(False)
    #         self._mw.load_injections_PushButton.setVisible(False)
    #         self._mw.dapi_path_Label.setVisible(False)
    #         self._mw.dapi_data_LineEdit.setVisible(False)
    #         self._mw.load_dapi_PushButton.setVisible(False)
    #         self._mw.time_step_Label.setVisible(False)
    #         self._mw.time_step_SpinBox.setVisible(False)
    #         self._mw.save_remote_path_Label.setVisible(False)
    #         self._mw.save_network_path_LineEdit.setVisible(False)
    #         self._mw.TransferData_checkBox.setVisible(False)
    #         self._mw.num_iterations_Label.setVisible(False)
    #         self._mw.num_iterations_SpinBox.setVisible(False)
    #
    #         # Modify the laser list in order to add the bright field control
    #         self._mw.laser_ComboBox.addItems(['Brightfield'])
    #
    #     elif experiment == 'Timelapse RAMM':
    #         # change the listview model
    #         self._mw.imaging_sequence_ListView.setModel(self._exp_logic.img_sequence_model_timelapse_ramm)
    #         self._exp_logic.is_timelapse_ramm = True
    #         self._exp_logic.is_timelapse_palm = False
    #
    #         self._mw.formWidget.setVisible(True)
    #         self.set_visibility_general_settings(True)
    #         self.set_visibility_camera_settings(True)
    #         self.set_visibility_filter_settings(False)
    #         self.set_visibility_imaging_settings(True)
    #         self.set_visibility_save_settings(True)
    #         self.set_visibility_scan_settings(True)
    #         self.set_visibility_documents_settings(True)
    #         self.set_visibility_prebleaching_settings(False)
    #         self.set_visibility_timelapse_settings(True)
    #         self.set_visibility_ZEN_security_settings(False)
    #
    #         # additional visibility modifications
    #         self._mw.gain_Label.setVisible(False)
    #         self._mw.gain_SpinBox.setVisible(False)
    #         self._mw.get_gain_PushButton.setVisible(False)
    #         self._mw.num_frames_Label.setVisible(False)
    #         self._mw.num_frames_SpinBox.setVisible(False)
    #         self._mw.injections_list_Label.setVisible(False)
    #         self._mw.injections_list_LineEdit.setVisible(False)
    #         self._mw.load_injections_PushButton.setVisible(False)
    #         self._mw.dapi_path_Label.setVisible(False)
    #         self._mw.dapi_data_LineEdit.setVisible(False)
    #         self._mw.load_dapi_PushButton.setVisible(False)
    #         self._mw.dz_calibration_label.setVisible(False)
    #         self._mw.axial_calibration_path_lineEdit.setVisible(False)
    #         self._mw.load_dz_calibration_pushButton.setVisible(False)
    #         self._mw.save_remote_path_Label.setVisible(False)
    #         self._mw.save_network_path_LineEdit.setVisible(False)
    #         self._mw.TransferData_checkBox.setVisible(False)
    #
    #         # Modify the laser list in order to add the bright field control
    #         self._mw.laser_ComboBox.addItems(['Brightfield'])
    #
    #     elif experiment == 'Timelapse PALM':
    #         # change the listview model
    #         self._mw.imaging_sequence_ListView.setModel(self._exp_logic.img_sequence_model_timelapse_palm)
    #         self._exp_logic.is_timelapse_ramm = False
    #         self._exp_logic.is_timelapse_palm = True
    #
    #         self._mw.formWidget.setVisible(True)
    #         self.set_visibility_general_settings(True)
    #         self.set_visibility_camera_settings(True)
    #         self.set_visibility_filter_settings(True)
    #         self.set_visibility_imaging_settings(True)
    #         self.set_visibility_save_settings(True)
    #         self.set_visibility_scan_settings(True)
    #         self.set_visibility_documents_settings(True)
    #         self.set_visibility_prebleaching_settings(False)
    #         self.set_visibility_timelapse_settings(True)
    #         self.set_visibility_ZEN_security_settings(False)
    #
    #         # additional visibility modifications
    #         self._mw.num_frames_Label.setVisible(False)
    #         self._mw.num_frames_SpinBox.setVisible(False)
    #         self._mw.injections_list_Label.setVisible(False)
    #         self._mw.injections_list_LineEdit.setVisible(False)
    #         self._mw.load_injections_PushButton.setVisible(False)
    #         self._mw.dapi_path_Label.setVisible(False)
    #         self._mw.dapi_data_LineEdit.setVisible(False)
    #         self._mw.load_dapi_PushButton.setVisible(False)
    #         self._mw.dz_calibration_label.setVisible(False)
    #         self._mw.axial_calibration_path_lineEdit.setVisible(False)
    #         self._mw.load_dz_calibration_pushButton.setVisible(False)
    #         self._mw.save_remote_path_Label.setVisible(False)
    #         self._mw.save_network_path_LineEdit.setVisible(False)
    #         self._mw.TransferData_checkBox.setVisible(False)
    #
    #     # add here additional experiment types
    #
    #     else:
    #         pass

    def set_visibility_general_settings(self, visible):
        """ Show or hide the block with the general settings widgets.
        :param bool visible: show widgets = True, hide widgets = False
        """
        self._mw.general_Label.setVisible(visible)
        self._mw.sample_name_Label.setVisible(visible)
        self._mw.sample_name_LineEdit.setVisible(visible)

        # the dapi and rna checkboxes are needed only for the ROI Multicolor scan RAMM. Set them invisible as default.
        self._mw.dapi_CheckBox.setVisible(False)
        self._mw.rna_CheckBox.setVisible(False)
        # same for the mail. It is only required for the HiM tasks
        self._mw.mail_LineEdit.setVisible(False)
        self._mw.mail_Label.setVisible(False)

    def set_visibility_camera_settings(self, visible):
        """ Show or hide the block with the camera settings widgets.
        :param bool visible: show widgets = True, hide widgets = False
        """
        self._mw.cam_settings_Label.setVisible(visible)
        self._mw.exposure_Label.setVisible(visible)
        self._mw.exposure_DSpinBox.setVisible(visible)
        self._mw.get_exposure_PushButton.setVisible(visible)
        self._mw.gain_Label.setVisible(visible)
        self._mw.gain_SpinBox.setVisible(visible)
        self._mw.get_gain_PushButton.setVisible(visible)
        self._mw.num_frames_Label.setVisible(visible)
        self._mw.num_frames_SpinBox.setVisible(visible)

    def set_visibility_filter_settings(self, visible):
        """ Show or hide the block with the filter settings widgets.
        :param bool visible: show widgets = True, hide widgets = False
        """
        self._mw.filter_settings_Label.setVisible(visible)
        self._mw.filterpos_Label.setVisible(visible)
        self._mw.filterpos_ComboBox.setVisible(visible)
        self._mw.get_filterpos_PushButton.setVisible(visible)

    def set_visibility_imaging_settings(self, visible):
        """ Show or hide the block with the imaging sequence widgets.
        :param bool visible: show widgets = True, hide widgets = False
        """
        self._mw.imaging_settings_Label.setVisible(visible)
        self._mw.imaging_sequence_Label.setVisible(visible)
        self._mw.imaging_sequence_ListView.setVisible(visible)
        self._mw.laser_ComboBox.setVisible(visible)
        self._mw.laser_intensity_DSpinBox.setVisible(visible)
        self._mw.delete_entry_PushButton.setVisible(visible)
        self._mw.add_entry_PushButton.setVisible(visible)
        self._mw.delete_all_PushButton.setVisible(visible)

    def set_visibility_save_settings(self, visible):
        """ Show or hide the block with the save settings widgets. (Information where to save image data, and fileformat)
        :param bool visible: show widgets = True, hide widgets = False
        """
        self._mw.save_settings_Label.setVisible(visible)
        self._mw.save_path_Label.setVisible(visible)
        self._mw.save_remote_path_Label.setVisible(visible)
        self._mw.save_path_LineEdit.setVisible(visible)
        self._mw.save_network_path_LineEdit.setVisible(visible)
        self._mw.fileformat_Label.setVisible(visible)
        self._mw.fileformat_ComboBox.setVisible(visible)
        self._mw.TransferData_checkBox.setVisible(visible)

        # the saving settings for ZEN have been added here. By default, they are set to invisible.
        self._mw.Zen_saving_folder_Label.setVisible(False)
        self._mw.Zen_saving_folder_lineEdit.setVisible(False)
        self._mw.Zen_saving_folder_pushButton.setVisible(False)

    def set_visibility_scan_settings(self, visible):
        """ Show or hide the block with the scan settings widgets.
        :param bool visible: show widgets = True, hide widgets = False
        """
        self._mw.scan_settings_Label.setVisible(visible)
        self._mw.num_z_planes_Label.setVisible(visible)
        self._mw.num_z_planes_SpinBox.setVisible(visible)
        self._mw.z_step_Label.setVisible(visible)
        self._mw.z_step_DSpinBox.setVisible(visible)
        self._mw.centered_focal_plane_CheckBox.setVisible(visible)

    def set_visibility_documents_settings(self, visible):
        """ Show or hide the block with the additional documents settings widgets.
        :param bool visible: show widgets = True, hide widgets = False
        """
        self._mw.documents_Label.setVisible(visible)
        self._mw.roi_list_path_Label.setVisible(visible)
        self._mw.roi_list_path_LineEdit.setVisible(visible)
        self._mw.load_roi_PushButton.setVisible(visible)
        self._mw.injections_list_Label.setVisible(visible)
        self._mw.injections_list_LineEdit.setVisible(visible)
        self._mw.load_injections_PushButton.setVisible(visible)

        # the following items were used for Bokeh - DEPRECATED
        self._mw.dapi_path_Label.setVisible(False)
        self._mw.dapi_data_LineEdit.setVisible(False)
        self._mw.load_dapi_PushButton.setVisible(False)

    def set_visibility_prebleaching_settings(self, visible):
        """ Show or hide the block with the prebleaching settings widgets
        :param bool visible: show widgets = True, hide widgets = False
        """
        self._mw.prebleach_settings_Label.setVisible(visible)
        self._mw.illumination_time_Label.setVisible(visible)
        self._mw.illumination_time_DSpinBox.setVisible(visible)

    def set_visibility_timelapse_settings(self, visible):
        """ Show or hide the block with the timelapse settings widgets.
        :param bool visible: show widgets = True, hide widgets = False """
        self._mw.timelapse_settings_Label.setVisible(visible)
        self._mw.num_iterations_Label.setVisible(visible)
        self._mw.num_iterations_SpinBox.setVisible(visible)
        self._mw.time_step_Label.setVisible(visible)
        self._mw.time_step_SpinBox.setVisible(visible)
        self._mw.dz_calibration_label.setVisible(visible)
        self._mw.axial_calibration_path_lineEdit.setVisible(visible)
        self._mw.load_dz_calibration_pushButton.setVisible(visible)

    def set_visibility_ZEN_security_settings(self, visible):
        """ Show or hide the block with the timelapse settings widgets.
        :param bool visible: show widgets = True, hide widgets = False """
        self._mw.Autofocus_security_Label.setVisible(visible)
        self._mw.reference_image_folder_Label.setVisible(visible)
        self._mw.reference_images_lineEdit.setVisible(visible)
        self._mw.reference_images_pushButton.setVisible(visible)
        self._mw.Correlation_threshold_Label.setVisible(visible)
        self._mw.Zen_correlation_DSpinBox.setVisible(visible)

# ----------------------------------------------------------------------------------------------------------------------
# Callbacks of the toolbuttons
# ----------------------------------------------------------------------------------------------------------------------

    def save_config_clicked(self):
        """ Callback of the save config toolbutton. Sends a signal to the logic indicating the complete path where
         the config file will be saved depending on the experimental setup, and the experiment.
        A default filename is used in the logic module which is linked to the taskrunner (experiments are run using the
        parameters in these default files.
        """
        path = os.path.join(self.default_location, 'qudi_task_config_files')
        experiment = self._mw.select_experiment_ComboBox.currentText()
        self.sigSaveConfig.emit(path, experiment, None)

    def save_config_copy_clicked(self):
        """ Callback of the save config copy toolbutton. Sends a signal to the logic indicating the complete path where
         the config file will be saved depending on the experimental setup, the experiment, and a custom filename.
         The experiment will not be run based on the parameters in the custom file, this just serves as a backup for
         the user.
        """
        path = os.path.join(self.default_location, 'qudi_task_config_files')
        experiment = self._mw.select_experiment_ComboBox.currentText()
        this_file = QtWidgets.QFileDialog.getSaveFileName(self._mw, 'Save copy of experimental configuration',
                                                          path, 'yaml files (*.yaml)')[0]
        path, filename = os.path.split(this_file)
        if this_file:
            self.sigSaveConfig.emit(path, experiment, filename)

    def load_config_clicked(self):
        """ Callback of the load config toolbutton. Opens a dialog to select an already defined config file. """
        data_directory = os.path.join(self.default_location, 'qudi_task_config_files')
        this_file = QtWidgets.QFileDialog.getOpenFileName(self._mw,
                                                          'Open experiment configuration',
                                                          data_directory,
                                                          'yaml files (*.yaml)')[0]
        if this_file:
            self.sigLoadConfig.emit(this_file)

    def clear_all_clicked(self):
        """Reset the selected experiment to its YAML defaults."""
        experiment = (
            self._mw
            .select_experiment_ComboBox
            .currentText()
        )

        if experiment == "Select your experiment..":
            return

        self._exp_logic.init_config_from_definition(experiment)
        self.update_entries()
        self._mw.laser_ComboBox.setCurrentIndex(0)
        self._mw.laser_intensity_DSpinBox.setValue(0.0)

# ----------------------------------------------------------------------------------------------------------------------
# Callbacks of pushbuttons on the configuration form
# ----------------------------------------------------------------------------------------------------------------------

    def add_entry_clicked(self):
        """ Callback of add entry pushbutton inserting an item into the imaging sequence list. """
        lightsource = self._mw.laser_ComboBox.currentText()  # or replace by current index
        intensity = self._mw.laser_intensity_DSpinBox.value()

        if self._exp_logic.is_timelapse_ramm:
            num_z_planes = self._mw.num_z_planes_SpinBox.value()
            z_step = self._mw.z_step_DSpinBox.value()
            filter_pos = 0

        elif self._exp_logic.is_timelapse_palm:
            num_z_planes = self._mw.num_z_planes_SpinBox.value()
            z_step = self._mw.z_step_DSpinBox.value()
            filter_pos = self._mw.filterpos_ComboBox.currentIndex() + 1

        else:
            # dummy values
            num_z_planes = 0
            z_step = 0
            filter_pos = 0

        self.sigAddEntry.emit(lightsource, intensity, num_z_planes, z_step, filter_pos)

    def delete_entry_clicked(self):
        """ Callback of delete entry pushbutton. The selected item is deleted from the list model in the logic module.
        """
        indexes = self._mw.imaging_sequence_ListView.selectedIndexes()
        if indexes:
            # Indexes is a list of a single item in single-select mode.
            index = indexes[0]
            self.sigDeleteEntry.emit(index)

    def load_roi_list_clicked(self):
        """ Callback of load roi pushbutton. Opens a dialog to select the complete path to the roi list.
        """
        data_directory = os.path.join(self.default_location, 'qudi_roi_lists')
        this_file = QtWidgets.QFileDialog.getOpenFileName(self._mw,
                                                          'Open ROI list',
                                                          data_directory,
                                                          'json files (*.json)')[0]
        if this_file:
            self._mw.roi_list_path_LineEdit.setText(this_file)

    def load_injections_clicked(self):
        """ Callback of load injections pushbutton. Opens a dialog to select the complete path to the injections list.
        """
        data_directory = os.path.join(self.default_location, 'qudi_injection_parameters')
        this_file = QtWidgets.QFileDialog.getOpenFileName(self._mw,
                                                          'Open injections file',
                                                          data_directory,
                                                          'yaml files (*.yaml)')[0]
        # print(this_file)
        if this_file:
            self._mw.injections_list_LineEdit.setText(this_file)

    def load_dapi_path_clicked(self):
        """ Callback of load dapi path pushbutton. Opens a dialog to select the complete path to the folder with
        the associated dapi data, needed for data visualization and processing for experiment tracker app and / or
        simultaneous data analysis during a Hi-M experiment.
        """
        this_dir = QtWidgets.QFileDialog.getExistingDirectory(self._mw,
                                                          'Open DAPI directory',
                                                          '/home')  # to be changed using a correct path stem
        if this_dir:
            self._mw.dapi_data_LineEdit.setText(this_dir)

    def load_ref_images_path_clicked(self):
        """ Callback of reference_images pushbutton. Opens a dialog to select the complete path to the folder with
        the reference images, needed for the procedure checking the autofocus for the airyscan microscope.
        """
        this_dir = QtWidgets.QFileDialog.getExistingDirectory(self._mw,
                                                          'Open directory where reference images are saved',
                                                          r'W:')  # to be changed using a correct path stem
        if this_dir:
            self._mw.reference_images_lineEdit.setText(this_dir)

    def load_zen_saving_path_clicked(self):
        """ Callback of reference_images pushbutton. Opens a dialog to select the complete path to the folder where the
        data will be saved, needed for the procedure checking the autofocus for the airyscan microscope.
        """
        this_dir = QtWidgets.QFileDialog.getExistingDirectory(self._mw,
                                                          'Open directory where data are saved',
                                                          r"W:")  # to be changed using a correct path stem
        if this_dir:
            self._mw.Zen_saving_folder_lineEdit.setText(this_dir)

    def load_axial_calibration_path_clicked(self):
        """ Callback of load axial calibration path pushbutton. Opens a dialog to select the complete path to the folder
        with the associated calibration data. This file can be used for TFL experiment in order to skip the autofocus
        calibration.
        """
        # data_directory = os.path.join(self.default_location, 'qudi_roi_lists')
        this_file = QtWidgets.QFileDialog.getOpenFileName(self._mw,
                                                          'Open axial calibration file')[0]
        if this_file:
            self._mw.axial_calibration_path_lineEdit.setText(this_file)

# ----------------------------------------------------------------------------------------------------------------------
# Callbacks of signals sent from the logic
# ----------------------------------------------------------------------------------------------------------------------

    def update_entries(self):
        """ Callback of the signal sigConfigDictUpdated sent from the logic. Updates the values on the configuration
        form using the values stored in the config dict in the logic module. """
        blockers = [QtCore.QSignalBlocker(widget) for widget in self._configuration_input_widgets()]
        try:
            config = self._exp_logic.config_dict
            self._mw.sample_name_LineEdit.setText(self._exp_logic.config_dict.get('sample_name', ''))
            self._mw.exposure_DSpinBox.setValue(self._exp_logic.config_dict.get('exposure', 0.0))
            self._mw.gain_SpinBox.setValue(self._exp_logic.config_dict.get('gain', 0))
            self._mw.num_frames_SpinBox.setValue(self._exp_logic.config_dict.get('num_frames', 1))
            self._mw.filterpos_ComboBox.setCurrentIndex(self._exp_logic.config_dict.get('filter_pos', 1) - 1)  # zero indexing
            self._exp_logic.img_sequence_model.layoutChanged.emit()
            self._exp_logic.img_sequence_model_timelapse_ramm.layoutChanged.emit()
            self._exp_logic.img_sequence_model_timelapse_palm.layoutChanged.emit()
            self._mw.save_path_LineEdit.setText(self._exp_logic.config_dict.get('save_path', ''))
            self._mw.save_network_path_LineEdit.setText(self._exp_logic.config_dict.get('save_network_path', ''))
            self._mw.TransferData_checkBox.setChecked(self._exp_logic.config_dict.get('transfer_data', False))
            self._mw.fileformat_ComboBox.setCurrentText(self._exp_logic.config_dict.get('file_format', ''))
            self._mw.num_z_planes_SpinBox.setValue(self._exp_logic.config_dict.get('num_z_planes', 1))
            self._mw.z_step_DSpinBox.setValue(self._exp_logic.config_dict.get('z_step', 0.0))
            self._mw.centered_focal_plane_CheckBox.setChecked(
                self._exp_logic.config_dict.get('centered_focal_plane', False))
            self._mw.roi_list_path_LineEdit.setText(self._exp_logic.config_dict.get('roi_list_path', ''))
            self._mw.injections_list_LineEdit.setText(self._exp_logic.config_dict.get('injections_path', ''))
            self._mw.dapi_data_LineEdit.setText(self._exp_logic.config_dict.get('dapi_path', ''))
            self._mw.reference_images_lineEdit.setText(self._exp_logic.config_dict.get('zen_ref_images_path', ''))
            self._mw.Zen_saving_folder_lineEdit.setText(self._exp_logic.config_dict.get('zen_saving_path', ''))
            self._mw.illumination_time_DSpinBox.setValue(self._exp_logic.config_dict.get('illumination_time', 0.0))
            self._mw.num_iterations_SpinBox.setValue(self._exp_logic.config_dict.get('num_iterations', 0))
            self._mw.time_step_SpinBox.setValue(self._exp_logic.config_dict.get('time_step', 0))
            self._mw.axial_calibration_path_lineEdit.setText(self._exp_logic.config_dict.get('axial_calibration_path', ''))
            self._mw.mail_LineEdit.setText(self._exp_logic.config_dict.get('email', ''))
            self._mw.Zen_correlation_DSpinBox.setValue(self._exp_logic.config_dict.get('correlation_threshold', 0.6))

            self._exp_logic.img_sequence_model.layoutChanged.emit()
            self._exp_logic.img_sequence_model_timelapse_ramm.layoutChanged.emit()
            self._exp_logic.img_sequence_model_timelapse_palm.layoutChanged.emit()

        finally:
            del blockers

    def update_listview(self):
        """ Callback of the signal sigImagingListChanged sent from the logic. Updates the items displayed in the
        imaging sequence listview. """
        self._exp_logic.img_sequence_model.layoutChanged.emit()
        self._exp_logic.img_sequence_model_timelapse_ramm.layoutChanged.emit()
        self._exp_logic.img_sequence_model_timelapse_palm.layoutChanged.emit()
        # for the delete entry case, if one row is selected then it will be deleted
        indexes = self._mw.imaging_sequence_ListView.selectedIndexes()
        if indexes:
            self._mw.imaging_sequence_ListView.clearSelection()

    def display_loaded_config(self):
        """ Callback of the signal sigConfigLoaded sent from the logic. Updates the displayed configuration form
        according to the experiment and shows the values defined in the loaded config file. """

        experiment = self._exp_logic.config_dict["experiment"]
        selector_blocker = QtCore.QSignalBlocker(self._mw.select_experiment_ComboBox)

        try:
            self._mw.select_experiment_ComboBox.setCurrentText(experiment)
        finally:
            del selector_blocker

        definition = self._exp_logic.experiment_definitions[experiment]
        self.apply_experiment_definition(definition)
        self.update_entries()

    def update_list_model(self, model):
        """ """
        if model == 1:  # timelapse ramm
            self._mw.imaging_sequence_ListView.setModel(self._exp_logic.img_sequence_model_timelapse_ramm)
        elif model == 2:  # timelapse palm
            self._mw.imaging_sequence_ListView.setModel(self._exp_logic.img_sequence_model_timelapse_palm)
        else:  # standard listview model (lightsource, intensity)
            self._mw.imaging_sequence_ListView.setModel(self._exp_logic.img_sequence_model)

# ----------------------------------------------------------------------------------------------------------------------
# Private methods
# ----------------------------------------------------------------------------------------------------------------------

    def _configuration_input_widgets(self):
        return (
            self._mw.sample_name_LineEdit,
            self._mw.mail_LineEdit,
            self._mw.dapi_CheckBox,
            self._mw.rna_CheckBox,
            self._mw.TransferData_checkBox,
            self._mw.exposure_DSpinBox,
            self._mw.gain_SpinBox,
            self._mw.num_frames_SpinBox,
            self._mw.filterpos_ComboBox,
            self._mw.save_path_LineEdit,
            self._mw.save_network_path_LineEdit,
            self._mw.fileformat_ComboBox,
            self._mw.num_z_planes_SpinBox,
            self._mw.z_step_DSpinBox,
            self._mw.centered_focal_plane_CheckBox,
            self._mw.roi_list_path_LineEdit,
            self._mw.injections_list_LineEdit,
            self._mw.dapi_data_LineEdit,
            self._mw.reference_images_lineEdit,
            self._mw.Zen_saving_folder_lineEdit,
            self._mw.Zen_correlation_DSpinBox,
            self._mw.illumination_time_DSpinBox,
            self._mw.num_iterations_SpinBox,
            self._mw.time_step_SpinBox,
            self._mw.axial_calibration_path_lineEdit,
        )
