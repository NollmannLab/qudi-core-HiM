# -*- coding: utf-8 -*-
"""
qudi-core-HiM: data folder of a task run (ROI scan, Hi-M), created by qudi.

  - choose_data_root(task, network_path, local_path): the folder under which the run folder is created.
    The server folder (network_path) when it is set and writable; otherwise, or if the server folder is
    not reachable (warning in the log and non-modal warning pop-up), the local folder (local_path).
    Error if the folder finally chosen cannot be written. Called before any hardware call.
  - create_run_folder(root, kind, sample_name, suffix=''): root/YYYY_MM_DD/NNN_<kind>_<sample><suffix>,
    NNN = number of folders already in root/YYYY_MM_DD + 1, on 3 digits.

Modified with Claude code (Anthropic)

-----------------------------------------------------------------------------------
qudi-core is free software: you can redistribute it and/or modify it under the terms of the GNU General Public License
as published by the Free Software Foundation, either version 3 of the License, or (at your option) any later version.

Qudi is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU General Public License for more details.

You should have received a copy of the GNU General Public License along with Qudi. If not, see <http://www.gnu.org/licenses/>.
-----------------------------------------------------------------------------------
"""

__all__ = ['choose_data_root', 'create_run_folder']

import os
import uuid
from datetime import datetime

from qudi.tasks.common.popups import show_warning_popup

SERVER_WARNING_TITLE = 'Server folder not reachable'


def _day_folder(root) -> str:
    return os.path.join(root, datetime.today().strftime('%Y_%m_%d'))


def _write_test(root) -> None:
    """Create root/YYYY_MM_DD (if needed), write and remove a small test file there. Raises OSError."""
    day_folder = _day_folder(root)
    os.makedirs(day_folder, exist_ok=True)
    test_file = os.path.join(day_folder, f'.qudi_write_test_{uuid.uuid4().hex}')
    with open(test_file, 'w') as stream:
        stream.write('qudi write test\n')
    os.remove(test_file)


def choose_data_root(task, network_path, local_path) -> str:
    """network_path if it is set and writable, else local_path (server problem: warning in the task log and
    non-modal pop-up). Raises RuntimeError if local_path is needed and cannot be written."""
    network_path = str(network_path).strip() if network_path else ''
    if network_path:
        try:
            _write_test(network_path)
        except OSError as err:
            text = (f'The server folder {network_path} is not reachable ({err}). The metadata are saved locally '
                    f'in {local_path}.')
            task.log.warning(text)
            show_warning_popup(SERVER_WARNING_TITLE, text)
        else:
            task.log.info(f'Data of this run saved on the server folder {network_path}')
            return network_path
    if not local_path:
        raise RuntimeError("No local data folder (experiment file key 'save_path').")
    try:
        _write_test(local_path)
    except OSError as err:
        raise RuntimeError(f'The local data folder {local_path} cannot be written ({err}).') from err
    task.log.info(f'Data of this run saved in the local folder {local_path}')
    return local_path


def create_run_folder(root, kind, sample_name, suffix=''):
    """Create root/YYYY_MM_DD/NNN_<kind>_<sample_name><suffix> and return (path, NNN); NNN = number of
    folders already in root/YYYY_MM_DD + 1, on 3 digits."""
    day_folder = _day_folder(root)
    os.makedirs(day_folder, exist_ok=True)
    folders = [name for name in os.listdir(day_folder) if os.path.isdir(os.path.join(day_folder, name))]
    prefix = str(len(folders) + 1).zfill(3)
    path = os.path.join(day_folder, f'{prefix}_{kind}_{sample_name}{suffix}')
    os.makedirs(path)
    return path, prefix
