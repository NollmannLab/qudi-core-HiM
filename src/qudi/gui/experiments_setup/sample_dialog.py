# -*- coding: utf-8 -*-
"""
qudi-core-HiM: dialog editing a sample file (tasks/common/sample_info.py), opened from the experiment
configurator ("Edit" button of the sample file). The form is generated from the sample template, one row per
field (QFormLayout; label = field name with '_' replaced by a space, '*' for a required field):

  - text   -> QLineEdit;
  - choice -> editable QComboBox: an empty entry first (an optional field can stay empty), then the choices;
              any other value can be typed (a loaded value that is not a choice is shown as typed text);
  - number -> QDoubleSpinBox with the min / max of the template. Empty state: the spin box minimum is one step
              below the allowed minimum and shows the special value text '-' (value None in the file).

Buttons: "Save" (overwrites the file the dialog was opened with; disabled for a new sample), "Save as..." (file
dialog in the default folder of the sample files, '.yml' added when missing) and "Cancel". Saving is refused
while a required field is empty (message box listing them). After a save, saved_path holds the path written.
Values of fields that are not in the template are kept.

Modified with Claude code (Anthropic)

-----------------------------------------------------------------------------------
qudi-core is free software: you can redistribute it and/or modify it under the terms of the GNU General Public License
as published by the Free Software Foundation, either version 3 of the License, or (at your option) any later version.

Qudi is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU General Public License for more details.

You should have received a copy of the GNU General Public License along with Qudi. If not, see <http://www.gnu.org/licenses/>.
-----------------------------------------------------------------------------------
"""

__all__ = ['SampleDialog', 'EMPTY_NUMBER_TEXT']

import os

from qtpy import QtWidgets

from qudi.tasks.common.sample_info import missing_required, save_sample_file

EMPTY_NUMBER_TEXT = '-'      # shown by a number field left empty
NUMBER_RANGE = 1e9           # range of a number field without min / max
NUMBER_STEP = 1.0
NUMBER_DECIMALS = 2


class SampleDialog(QtWidgets.QDialog):
    """Form of a sample file generated from the sample template (see module docstring).

    Args:
        template: field definitions (sample_info.load_sample_template).
        values: content of the sample file opened ({} for a new sample).
        path: file the dialog was opened with ('' for a new sample): target of "Save".
        default_folder: start folder of "Save as..." when path is empty.
    """

    def __init__(self, template, values=None, path='', default_folder='', parent=None):
        super().__init__(parent)
        self._template = list(template)
        self._loaded = dict(values or {})
        self._path = path or ''
        self._default_folder = default_folder or ''
        self.saved_path = ''
        self.widgets = {}
        self.setWindowTitle(f'Sample file - {os.path.basename(self._path)}' if self._path else 'Sample file - new sample')

        form = QtWidgets.QFormLayout()
        for definition in self._template:
            name = definition['name']
            widget = self._make_widget(definition)
            self._set_value(definition, widget, self._loaded.get(name))
            label = name.replace('_', ' ') + (' *' if definition['required'] else '')
            form.addRow(label, widget)
            self.widgets[name] = widget

        self.save_button = QtWidgets.QPushButton('Save')
        self.save_button.setEnabled(bool(self._path))
        self.save_button.setToolTip('Overwrite the sample file' if self._path else 'No file yet: use "Save as..."')
        self.save_as_button = QtWidgets.QPushButton('Save as...')
        self.cancel_button = QtWidgets.QPushButton('Cancel')
        self.save_button.clicked.connect(self.save)
        self.save_as_button.clicked.connect(self.save_as)
        self.cancel_button.clicked.connect(self.reject)
        buttons = QtWidgets.QHBoxLayout()
        buttons.addStretch(1)
        for button in (self.save_button, self.save_as_button, self.cancel_button):
            buttons.addWidget(button)

        note = QtWidgets.QLabel('* required')
        layout = QtWidgets.QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(note)
        layout.addLayout(buttons)

    # ------------------------------------------------------------------ widgets of the fields
    @staticmethod
    def _make_widget(definition):
        if definition['type'] == 'choice':
            widget = QtWidgets.QComboBox()
            widget.setEditable(True)
            widget.setInsertPolicy(QtWidgets.QComboBox.InsertPolicy.NoInsert)
            widget.addItems([''] + definition['choices'])  # empty entry first: the field can stay empty
            return widget
        if definition['type'] == 'number':
            widget = QtWidgets.QDoubleSpinBox()
            low = definition['min'] if definition['min'] is not None else -NUMBER_RANGE
            high = definition['max'] if definition['max'] is not None else NUMBER_RANGE
            widget.setDecimals(NUMBER_DECIMALS)
            widget.setSingleStep(NUMBER_STEP)
            # empty state: one step below the allowed minimum, shown as '-'
            widget.setRange(low - NUMBER_STEP, high)
            widget.setSpecialValueText(EMPTY_NUMBER_TEXT)
            return widget
        return QtWidgets.QLineEdit()

    @staticmethod
    def _set_value(definition, widget, value) -> None:
        if definition['type'] == 'choice':
            text = '' if value is None else str(value)
            index = widget.findText(text)
            if index >= 0:
                widget.setCurrentIndex(index)
            else:
                widget.setEditText(text)  # value that is not one of the choices: shown as typed text
        elif definition['type'] == 'number':
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                widget.setValue(float(value))
            else:
                widget.setValue(widget.minimum())  # empty
        else:
            widget.setText('' if value is None else str(value))

    @staticmethod
    def _get_value(definition, widget):
        if definition['type'] == 'choice':
            return widget.currentText().strip() or None
        if definition['type'] == 'number':
            if widget.value() == widget.minimum():
                return None  # empty state
            value = widget.value()
            return int(value) if float(value).is_integer() else value
        return widget.text().strip() or None

    # ------------------------------------------------------------------ values and saving
    def values(self) -> dict:
        """Values of the form: the loaded file's keys in their order (fields not in the template kept), then the
        template fields that were not in the file. Empty fields are None."""
        values = dict(self._loaded)
        for definition in self._template:
            values[definition['name']] = self._get_value(definition, self.widgets[definition['name']])
        return values

    def _show_warning(self, title, text) -> None:
        QtWidgets.QMessageBox.warning(self, title, text)

    def _write(self, path) -> bool:
        """Write the form in path, refused while a required field is empty; True when written."""
        values = self.values()
        missing = missing_required(self._template, values)
        if missing:
            self._show_warning('Sample file not saved',
                               'Required field(s) empty:\n  - ' + '\n  - '.join(n.replace('_', ' ') for n in missing))
            return False
        try:
            save_sample_file(path, values)
        except OSError as err:
            self._show_warning('Sample file not saved', f'{path} could not be written: {err}')
            return False
        self.saved_path = path
        self.accept()
        return True

    def save(self) -> bool:
        """Overwrite the file the dialog was opened with."""
        if not self._path:
            return False
        return self._write(self._path)

    def save_as(self) -> bool:
        """Ask for a file name (default folder of the sample files, '.yml' added when missing) and write it."""
        start = self._default_folder if os.path.isdir(self._default_folder) else os.path.dirname(self._path)
        path, _ = QtWidgets.QFileDialog.getSaveFileName(self, 'Save the sample file as', start or os.path.expanduser('~'),
                                                        'Sample files (*.yml)')
        if not path:
            return False
        if not path.lower().endswith('.yml'):
            path += '.yml'
        return self._write(path)
