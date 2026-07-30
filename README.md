# qudi-core-HiM

This repository contains HiM-specific modules for the current `qudi-core`
codebase. It is not the legacy Qudi tree. The code here is meant to work with
the modern [qudi-core](https://github.com/Ulm-IQO/qudi-core) package and its current interface/module structure.

This repository adds extra hardware, logic, interface, GUI, and utility modules to Qudi.
It does not replace Qudi. It is installed alongside Qudi in the same Python environment.

## Requirements

- Python 3.10 or newer
- Hardware-specific vendor software when required

The required `qudi-core` package is listed in `pyproject.toml`. This file is the installation configuration file for this repository.
It tells `pip`:

- the package name and version;
- the supported Python version;
- which packages are required;
- where the Python source files are located;
- which tool should build and install the package.

The most important part of the file is the following :
```toml
[project]
name = "qudi-core-him"
requires-python = ">=3.10"
dependencies = [
    "qudi-core"
]
```
It means that:
- the installed package is named `qudi-core-him`;
- Python 3.10 or newer is required;
- `qudi-core` is installed automatically when it is missing.

## Installation

### 1. Create a Python environment

Using Conda:

```bash
conda create -n qudi python=3.10
conda activate qudi
```

### 2. Clone this repository

```bash
git clone https://github.com/NollmannLab/qudi-core-HiM
cd qudi-core-HiM
```

### 3. Install the repository

```bash
python -m pip install -e .
```

The `-e` option means **editable installation**. During this step, `pip` also installs missing dependencies listed in `pyproject.toml`, including `qudi-core`.

## Using a local copy of `qudi-core`

Developers may work with a local checkout of `qudi-core` instead of the published package.
Install that local copy first:

```bash
python -m pip install -e /path/to/qudi-core
```

Then install this repository:

```bash
python -m pip install -e /path/to/qudi_core_cbs
```

Both commands must be run while the same Python environment is active.

## Checking the installation

Check that both packages are installed:

```bash
python -m pip show qudi-core
python -m pip show qudi-core-him
```

You can also check which Python interpreter is being used:

```bash
which python
```

On Windows:

```powershell
where python
```

The reported path should point to the environment in which Qudi was installed.

## Updating the repository

From the repository folder:

```bash
git pull --rebase
```

Because the installation is editable, source-code updates are normally available immediately.

Run the installation command again only when `pyproject.toml` or the dependencies have changed:

```bash
python -m pip install -e .
```

## Repository layout

```text
qudi_core_cbs/
├── pyproject.toml
├── README.md
├── config/
├── docs/
├── src/
│   └── qudi/
│       ├── hardware/
│       ├── interface/
│       ├── logic/
│       ├── gui/
│       ├── helpers/
│       └── interfuse/

└── tests/
```

Only folders that are currently used need to be present.

- `src/qudi/hardware/`: communication with physical devices
- `src/qudi/interfuse/`: emulated high-level instrument connected to a physical devices
- `src/qudi/interface/`: common method definitions shared by modules
- `src/qudi/logic/`: experiment control and coordination
- `src/qudi/gui/`: graphical user interfaces
- `src/qudi/helpers/`: shared helper functions
- `config/`: example Qudi configuration files
- `docs/`: additional documentation
- `tests/`: automated tests

## Hardware-specific dependencies

Some hardware modules require software supplied by the hardware manufacturer.
These packages are not always installed automatically because they may only be available from the vendor.

Examples may include:

- Fluigent SDK
- PI GCS libraries and `PIPython`
- MCC ULDAQ libraries and Python bindings
- device drivers or serial-port permissions

Read the relevant [hardware documentation](https://github.com/NollmannLab/qudi-core-HiM/tree/main/docs/qudi-HiM_hardware) before activating a hardware module.