# -*- coding: utf-8 -*-
"""
qudi-core-HiM: sample file - a small YAML file describing one biological sample (organism, preparation, dyes,
...), written once from the experiment configurator and attached to every run that saves images (Hi-M, ROI
multicolour scan). Pure functions, no Qt.

  - load_sample_template(path) -> list of field definitions, in file order: the template
    (custom_config/custom_metadata_templates/sample_template.yml) maps each field name to
    {type: text | choice | number, choices: [...], min: .., max: .., required: true | false}.
    ValueError for a template that does not follow this format.
  - load_sample_file(path) -> dict of the sample file (order kept). RuntimeError if the file is missing,
    unreadable or not a mapping.
  - save_sample_file(path, values): YAML, keys in the order of values, UTF-8, unicode kept, no sorting.
  - missing_required(template, values) -> names of the required fields that are empty.
  - read_sample(path) -> SampleFile (path, values, exact bytes): read once before any hardware call, so the
    run does not depend on the file afterwards.
  - optional_sample(path) -> SampleFile, or None when path is empty (experiment key sample_file is optional in
    the task code: absent or empty -> no sample file, nothing changes).
  - add_sample_to_run(folder, sample, metadata=None): <folder>/sample.yml (byte copy) and a 'Sample' section in
    metadata (template layout: list of one-key mappings; fields of an existing 'Sample' section of the
    metadata template keep their place).

Values of fields that are not in the template (e.g. a field later removed from the template) are kept: loading
and saving a file never drops them.

Modified with Claude code (Anthropic)

-----------------------------------------------------------------------------------
qudi-core is free software: you can redistribute it and/or modify it under the terms of the GNU General Public License
as published by the Free Software Foundation, either version 3 of the License, or (at your option) any later version.

Qudi is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU General Public License for more details.

You should have received a copy of the GNU General Public License along with Qudi. If not, see <http://www.gnu.org/licenses/>.
-----------------------------------------------------------------------------------
"""

__all__ = ['FIELD_TYPES', 'SAMPLE_COPY_NAME', 'SAMPLE_SECTION', 'SampleFile', 'load_sample_template',
           'load_sample_file', 'save_sample_file', 'missing_required', 'is_empty', 'read_sample',
           'optional_sample', 'add_sample_to_run']

import os
from dataclasses import dataclass, field

import yaml

FIELD_TYPES = ('text', 'choice', 'number')
FIELD_KEYS = ('type', 'choices', 'min', 'max', 'required')
SAMPLE_COPY_NAME = 'sample.yml'   # copy of the sample file in the metadata folder of a run
SAMPLE_SECTION = 'Sample'         # section of metadata.yml holding the sample file content


@dataclass
class SampleFile:
    """Sample file read before a run: its path, its values and its exact content (copied as sample.yml)."""
    path: str
    values: dict = field(default_factory=dict)
    content: bytes = b''


def _is_number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def load_sample_template(path) -> list:
    """Field definitions of the template, in file order: dicts with name, type, choices (list), min, max (None
    when not set) and required (bool). ValueError when the file cannot be read or does not follow the format."""
    try:
        with open(path, 'r', encoding='utf-8') as stream:
            raw = yaml.safe_load(stream)
    except (OSError, yaml.YAMLError) as err:
        raise ValueError(f'Sample template "{path}" could not be read: {err}') from err
    if not isinstance(raw, dict) or not raw:
        raise ValueError(f'Sample template "{path}": expected a mapping "field name: {{type: ...}}".')
    fields = []
    for name, definition in raw.items():
        where = f'Sample template "{path}", field {name!r}'
        if not isinstance(definition, dict):
            raise ValueError(f'{where}: expected a mapping such as {{type: text}}.')
        unknown = [key for key in definition if key not in FIELD_KEYS]
        if unknown:
            raise ValueError(f'{where}: unknown key(s) {unknown} (allowed: {", ".join(FIELD_KEYS)}).')
        kind = definition.get('type')
        if kind not in FIELD_TYPES:
            raise ValueError(f'{where}: type {kind!r} unknown (allowed: {", ".join(FIELD_TYPES)}).')
        choices = definition.get('choices', [])
        if choices is None:
            choices = []
        if not isinstance(choices, list):
            raise ValueError(f'{where}: choices must be a list.')
        low, high = definition.get('min'), definition.get('max')
        for key, value in (('min', low), ('max', high)):
            if value is not None and not _is_number(value):
                raise ValueError(f'{where}: {key} must be a number.')
            if value is not None and kind != 'number':
                raise ValueError(f'{where}: {key} is allowed for the type number only.')
        if low is not None and high is not None and low > high:
            raise ValueError(f'{where}: min ({low}) is larger than max ({high}).')
        required = definition.get('required', False)
        if not isinstance(required, bool):
            raise ValueError(f'{where}: required must be true or false.')
        fields.append({'name': str(name), 'type': kind, 'choices': [str(c) for c in choices],
                       'min': low, 'max': high, 'required': required})
    return fields


def load_sample_file(path) -> dict:
    """Content of a sample file (order kept; an empty file gives {}). RuntimeError if the file is missing,
    unreadable or not a mapping."""
    if not path or not os.path.isfile(path):
        raise RuntimeError(f'Sample file "{path}" does not exist.')
    try:
        with open(path, 'r', encoding='utf-8') as stream:
            values = yaml.safe_load(stream)
    except (OSError, yaml.YAMLError, UnicodeDecodeError) as err:
        raise RuntimeError(f'Sample file "{path}" could not be read: {err}') from err
    if values is None:
        return {}
    if not isinstance(values, dict):
        raise RuntimeError(f'Sample file "{path}" is not a mapping "field: value".')
    return values


def save_sample_file(path, values: dict) -> str:
    """Write values as YAML in path (keys in the order of values, UTF-8, unicode kept); returns path."""
    with open(path, 'w', encoding='utf-8') as stream:
        yaml.safe_dump(dict(values), stream, allow_unicode=True, sort_keys=False, default_flow_style=False)
    return path


def is_empty(value) -> bool:
    """None, a blank string or an empty list."""
    return value is None or (isinstance(value, str) and not value.strip()) or value == []


def missing_required(template: list, values: dict) -> list:
    """Names of the required fields of the template whose value is empty (or absent), in template order."""
    return [f['name'] for f in template if f['required'] and is_empty(values.get(f['name']))]


def read_sample(path) -> SampleFile:
    """Sample file of a run, read before any hardware call (RuntimeError if missing, unreadable or not a
    mapping); its bytes are kept for the copy written later in the metadata folder."""
    values = load_sample_file(path)
    with open(path, 'rb') as stream:
        content = stream.read()
    return SampleFile(path=str(path), values=values, content=content)


def optional_sample(path):
    """read_sample(path) for a non-empty path (RuntimeError as read_sample), None for an empty or absent one."""
    path = str(path or '').strip()
    return read_sample(path) if path else None


def add_sample_to_run(folder, sample, metadata=None) -> None:
    """Attach the sample file to a run: <folder>/sample.yml (exact copy of the file read before the run) and,
    with metadata (dict of metadata.yml), its values in the 'Sample' section. Nothing is done without a
    sample (sample None)."""
    if sample is None:
        return
    # exact copy of the sample file, as read before the run
    with open(os.path.join(folder, SAMPLE_COPY_NAME), 'wb') as stream:
        stream.write(sample.content)
    if metadata is None:
        return
    # 'Sample' section: one-key mappings as the other sections; a section of the template keeps its place and
    # its fields their order (new fields appended), otherwise the section is appended at the end
    section = metadata.get(SAMPLE_SECTION)
    if not isinstance(section, (list, dict)):
        metadata[SAMPLE_SECTION] = section = []
    for key, value in sample.values.items():
        if isinstance(section, dict):
            section[key] = value
            continue
        for item in section:
            if isinstance(item, dict) and key in item:
                item[key] = value
                break
        else:
            section.append({key: value})
