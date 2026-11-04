# -*- coding: utf-8 -*-
"""
qudi-core-HiM: files describing a task run, written in its run folder (ROI scan, Hi-M, PSF stack).

  - copy_experiment_file(user_config_path, folder): exact byte copy of the experiment file as
    <folder>/experiment_config.yaml.
  - load_metadata_template(path) -> dict: microscope metadata template (YAML, e.g.
    custom_config/custom_metadata_templates/Spinning_Disk_setup.cfg), section order kept.
  - set_metadata_field(metadata, section, key, value): set one field of a section of the template
    layout (a section is a list of one-key mappings, or a mapping); missing keys are added.
  - write_metadata(folder, metadata, name='metadata.yml'): YAML dump, keys in template order.
  - fill_run_metadata(template, sample_name, imaging_sequence, roi_positions, num_z_planes=None): copy of
    the template with Time and the Acquisition fields known to the ROI scan and Hi-M tasks.
  - optional_metadata_template(task): template of the task option metadata_template - None (one
    warning) when the option is not set, RuntimeError when the file is missing or unreadable.

Modified with Claude code (Anthropic)

-----------------------------------------------------------------------------------
qudi-core is free software: you can redistribute it and/or modify it under the terms of the GNU General Public License
as published by the Free Software Foundation, either version 3 of the License, or (at your option) any later version.

Qudi is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU General Public License for more details.

You should have received a copy of the GNU General Public License along with Qudi. If not, see <http://www.gnu.org/licenses/>.
-----------------------------------------------------------------------------------
"""

__all__ = ['copy_experiment_file', 'load_metadata_template', 'set_metadata_field', 'write_metadata',
           'fill_run_metadata', 'optional_metadata_template']

import copy
import os
import shutil
from datetime import datetime

from ruamel.yaml import YAML

EXPERIMENT_COPY_NAME = 'experiment_config.yaml'
NO_TEMPLATE_WARNING = 'no metadata template set - metadata.yml not written'


def copy_experiment_file(user_config_path, folder) -> str:
    """Byte copy of the experiment file as <folder>/experiment_config.yaml; returns the copy's path."""
    path = os.path.join(folder, EXPERIMENT_COPY_NAME)
    shutil.copyfile(user_config_path, path)
    return path


def load_metadata_template(path) -> dict:
    """Metadata template (YAML) as a dict, section order kept. RuntimeError if it cannot be read."""
    try:
        with open(path, 'r', encoding='utf-8') as f:
            template = YAML().load(f)
    except Exception as err:
        raise RuntimeError(f'Could not read metadata_template "{path}": {err}') from err
    return dict(template or {})


def set_metadata_field(metadata: dict, section: str, key: str, value) -> None:
    """Set metadata[section][key] for the template layout (a section is a list of one-key
    mappings, or a mapping); the key is added if missing. Other fields are left untouched.
    """
    content = metadata.get(section)
    if isinstance(content, list):
        for item in content:
            if isinstance(item, dict) and key in item:
                item[key] = value
                return
        content.append({key: value})
    elif isinstance(content, dict):
        content[key] = value
    else:
        metadata[section] = [{key: value}]


def write_metadata(folder, metadata: dict, name='metadata.yml') -> str:
    """Dump metadata as YAML in <folder>/<name> (keys in template order); returns the file's path."""
    path = os.path.join(folder, name)
    with open(path, 'w', encoding='utf-8') as f:
        YAML().dump(metadata, f)
    return path


def fill_run_metadata(template: dict, sample_name, imaging_sequence, roi_positions, num_z_planes=None) -> dict:
    """Copy of the template with Time (date-time) and the Acquisition fields sample_name, laser_lines and
    laser_power_(%) (imaging sequence order), number_z_planes (when given) and roi_list_(xyz) (one
    {roi name: [x, y, z]} entry per ROI of roi_positions {name: position}, in order). Other fields stay as in
    the template."""
    metadata = copy.deepcopy(template)
    metadata['Time'] = datetime.now().strftime('%m-%d-%Y, %H:%M:%S')
    sequence = list(imaging_sequence or [])
    fields = {'sample_name': sample_name,
              'laser_lines': [entry[0] for entry in sequence],
              'laser_power_(%)': [entry[1] for entry in sequence]}
    if num_z_planes is not None:
        fields['number_z_planes'] = num_z_planes
    fields['roi_list_(xyz)'] = [{name: [float(v) for v in position]} for name, position in roi_positions.items()]
    for key, value in fields.items():
        set_metadata_field(metadata, 'Acquisition', key, value)
    return metadata


def optional_metadata_template(task):
    """Template of the task option metadata_template: None, with one warning in the task log, when the option
    is not set; RuntimeError when the file does not exist or cannot be read. Called before any hardware
    call."""
    path = getattr(task, 'metadata_template', None)
    if path is None or not str(path).strip():
        task.log.warning(NO_TEMPLATE_WARNING)
        return None
    if not os.path.isfile(path):
        raise RuntimeError(f'metadata_template "{path}" is not an existing file.')
    return load_metadata_template(path)
