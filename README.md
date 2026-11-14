# PSAIFileHandler

Standardized simulation and experimental data file handler for OpenFOAM, COMSOL, and MATLAB, converting heterogeneous engineering datasets into CF-compliant NetCDF-4 / HDF5 hierarchical trees (`xarray.DataTree`).

---

## 1. Installation

Install `psaifilehandler` into your project using `uv` (recommended) or `pip`:

### Core Installation (COMSOL & NetCDF-4)
```bash
# Using uv
uv add psaifilehandler

# Using pip
pip install psaifilehandler
```

### With Optional Physics Drivers
- **MATLAB Driver** (requires local MATLAB desktop installation):
  ```bash
  uv add "psaifilehandler[matlab]"
  ```
- **OpenFOAM Driver**:
  ```bash
  uv add "psaifilehandler[openfoam]"
  ```
- **All Drivers**:
  ```bash
  uv add "psaifilehandler[all]"
  ```

---

## 2. Quickstart

### COMSOL Multiphysics Ingestion
Extract spatial fields (pressure, velocity) and parametric sweep conditions from `.txt`, `.csv`, or `.vtu` exports:

```python
from psaifilehandler import ComsolConverter

schema = {
    "variables": {"Flow": "Q_in", "Speed": "rot_rpm"},
    "volute": {
        "coordinates": ["x", "y"],
        "variables": {
            "pressure": "p",
            "velocity": ["u", "v"],
        },
    },
}

converter = ComsolConverter(data_schema=schema)

# Export directly to compressed, CF-1.8 NetCDF-4
converter.to_netcdf4(
    files={"volute": "data/comsol/Pump2D_MRFStudy_UltraFine_Volute.txt"},
    output_path="output/pump_run.nc",
)
```

### MATLAB MAT-file & Sweep Ingestion
Convert deeply nested MATLAB structs or multi-run parametric sweeps:

```python
from psaifilehandler import MATConverter, MATSweepConverter

# Single MAT file conversion
converter = MATConverter(
    mat_file_path="data/matlab/experiment_01.mat",
    config_path="config/dataset_config.json",
)
converter.to_netcdf4("output/experiment_01.nc")

# Parametric sweep across multiple runs
sweep_converter = MATSweepConverter(
    sweep_folder="data/matlab/sweep_runs/",
    structured_sweep_mapping=mapping,
)
dt = sweep_converter.to_datatree()
```

---

## 3. Package Structure

```text
src/psaifilehandler/
├── __init__.py         # Top-level unified API exports
├── py.typed            # PEP 561 typing marker
├── comsol/             # COMSOL parsers, alias resolver, and converter
│   ├── aliases.py
│   ├── converter.py
│   ├── header_parser.py
│   └── parsers/
├── matlab/             # MATLAB struct & cell deserializers, sweep converter
│   ├── accessors.py
│   ├── containers.py
│   ├── converter.py
│   ├── mat_file.py
│   └── sweep_converter.py
└── openfoam/           # OpenFOAM case and result handlers
```

---

## 4. Documentation & Specifications

- **COMSOL Converter Guide**: [docs/COMSOL_CONVERTER.md](file:///home/bruno/Documents/PSAIFileHandler/docs/COMSOL_CONVERTER.md)
- **MATLAB Converter Guide**: [docs/MATLAB_CONVERTER.md](file:///home/bruno/Documents/PSAIFileHandler/docs/MATLAB_CONVERTER.md)
- **Data Format & Architecture Guidelines**: [GEMINI.md](file:///home/bruno/Documents/PSAIFileHandler/GEMINI.md)

---

## 5. Development

Clone the repository and set up the development environment using `uv`:

```bash
git clone https://github.com/your-org/PSAIFileHandler.git
cd PSAIFileHandler

# Sync all optional drivers and development dependencies
uv sync --all-extras

# Run tests
uv run pytest tests/ -v

# Run linter
uv run ruff check --no-cache src/ tests/

# Build standalone distribution wheel and sdist
uv build
```
