# MATLAB Ingestion & NetCDF-4 Conversion Guide

The `src/matlab/` package provides a high-performance, object-oriented pipeline for reading complex MATLAB (`.mat`) simulation files and standardizing them into hierarchical, CF-1.8 compliant NetCDF-4 datasets (`xarray.DataTree`).

---

## 1. Overview & Architecture

MATLAB simulation outputs typically contain nested structs, struct arrays, and cell arrays produced by numerical solvers (COMSOL, OpenFOAM, ANSYS). The MATLAB ingestion subsystem is divided into two primary converter classes:

1. **`MATConverter` (Procedural & Flexible)**:
   - Encapsulates a `MATFile` connection to the MATLAB Engine.
   - Converts an explicitly constructed hierarchical mapping dictionary into an `xarray.DataTree` and serializes it to NetCDF-4.
   - Recommended when experiments require custom data transformation, filtering, or bespoke domain decomposition (e.g. separating single and multiple boundary probes).

2. **`MATSweepConverter` (Declarative & Automated)**:
   - Composes a `MATConverter` and provides a high-level facade.
   - Automatically builds the mapping dictionary from a concise, declarative schema using dot-notation path expressions (e.g., `'s.coords'`, `'s.tab[0, 1]'`).
   - Validates shape and spatial coordinate invariance ($\max |X_e - X_1| \le \text{atol}$) across all sweep runs before conversion.
   - Recommended for parametric sweeps where all simulation runs share the same mesh discretization and variable layout.

```text
src/matlab/
├── mat_file.py           # MATFile wrapper managing MATLAB engine lifecycle
├── containers.py         # CellArray, MATStruct, MATStructArray, deserializer
├── accessors.py          # PathAccessor dot-notation engine for structs/arrays
├── converter.py          # MATConverter: procedural mapping -> DataTree -> NetCDF-4
└── sweep_converter.py    # MATSweepConverter: declarative schema -> validated sweep
```

---

## 2. Mapping Dictionary Specification

The core bridge between raw MATLAB data and the NetCDF-4 hierarchy is the **Mapping Dictionary**. Both `MATConverter` and `MATSweepConverter` consume or build this structure.

### 2.1. Hierarchical Layout

```text
mapping = {
    # Optional root-level metadata / provenance attributes
    "attrs": {"project": "Centrifugal Pump Sweep", "author": "Research Group"},
    "metadata": "path/to/project_readme.txt",   # Filepath, raw text, or dict

    # Each non-reserved key defines an Experiment group: /{exp_name}/
    "run_01": {
        "metadata": "path/to/run_01_config.csv",  # Stored as string attribute
        "attrs": {"Operating_RPM": 1500, "inflow_rate": 0.05},

        # [OPTIONAL] Non-spatial experiment-level signals (NO node dimension)
        "time": np.array([0.0, 0.1, 0.2, ...]),  # (time: T)
        "variables": {
            "Operating_RPM": xr.DataArray(1500),
            "Volume_Avg_Temp": xr.DataArray(temp_signal, dims=["time"]),
        },

        # Domain decomposition: each sub-dictionary is a Geometry group: /{exp_name}/{geom_name}/
        "volute": {
            "coordinates": coords_array,         # (N_v, 3) or (N_v, 2) [m]
            "variables": {
                "Pressure": p_volute_array,      # (time, node) or (node)
                "Velocity": v_volute_array,      # (time, node, spatial)
            },
            "attrs": {"material": "steel"},
        },

        "impeller": {
            "coordinates": coords_impeller,      # (N_i, 3) [m]
            "variables": {
                "Pressure": p_impeller_array,
            },
        },
    },

    "run_02": { ... },
}
```

---

### 2.2. Level-by-Level Dictionary Keys

#### Root Level
| Key | Type | Description |
| :--- | :--- | :--- |
| `"attrs"` / `"root_attrs"` | `dict` | Global NetCDF attributes (e.g. title, conventions, author). |
| `"metadata"` / `"root_metadata"` | `str` \| `Path` \| `dict` | Embedded file or raw text stored as global provenance attributes. |
| `"<experiment_name>"` | `dict` | Any key not matching reserved attribute names defines an experiment group `/{experiment_name}/`. |

#### Experiment Level (`mapping["<experiment_name>"]`)
| Key | Type | Description |
| :--- | :--- | :--- |
| `"attrs"` | `dict` | Experiment-specific scalar attributes (e.g. RPM, ambient temperature). |
| `"metadata"` | `str` \| `Path` \| `dict` | Experiment-level solver logs, boundary condition tables, or parameter files. |
| `"time"` | `np.ndarray` \| `xr.DataArray` | 1D temporal coordinate array in seconds ($T$). |
| `"variables"` | `dict[str, Any]` | Experiment-level signals that do **not** have spatial nodes (e.g. volume averages, driving inputs). |
| `"<geometry_name>"` | `dict` | Geometry sub-group (e.g. `"inlet"`, `"matrix"`). In `single_mesh=True` mode, mesh keys are omitted and coordinates/variables sit directly at the experiment level. |

#### Geometry Level (`mapping["<experiment_name>"]["<geometry_name>"]`)
| Key | Type | Description |
| :--- | :--- | :--- |
| `"coordinates"` | `np.ndarray` \| `xr.DataArray` | 2D node coordinates array with shape $(N, d)$, where $d \in \{2, 3\}$. Cartesian coordinates in meters. |
| `"time"` | `np.ndarray` \| `xr.DataArray` | *(Optional)* Geometry-specific time vector if different from experiment time. |
| `"variables"` | `dict[str, Any]` | Spatially distributed field arrays (see auto-normalization rules below). |
| `"attrs"` / `"metadata"` | `dict` \| `Path` | Domain-specific metadata and physical attributes. |

---

### 2.3. Automatic Array Dimension Normalization

`MATConverter` automatically maps NumPy arrays, Pandas DataFrames, or raw MATLAB matrices into standard `xarray.DataArray` structures:

| Array Shape | Inferred Dimensions | Description |
| :--- | :--- | :--- |
| `(T,)` matching time | `(time)` | 1D time-series scalar (experiment-level or probe signal). |
| `(N,)` matching nodes | `(node)` | Steady-state spatial field over mesh nodes. |
| `(T, N)` or `(N, T)` | `(time, node)` | Transient spatial field. Automatically transposed so `time` is leading. |
| `(N, 2)` or `(N, 3)` | `(node, spatial)` | Steady-state vector field with `spatial` coordinates `['x', 'y']` or `['x', 'y', 'z']`. |
| `(T, N, 3)` or `(N, T, 3)`| `(time, node, spatial)` | Transient 3D vector field (e.g. velocity vectors). |

> [!TIP]
> You can pass an explicit `xr.DataArray` with custom dimensions and attributes (e.g. `units="Pa"`, `long_name="Static Pressure"`) into `"variables"`. `MATConverter` preserves these attributes without modification.

---

## 3. Quickstart Examples

### 3.1. Procedural Ingestion with `MATConverter`

Use `MATConverter` when you need full control over extracting and transforming variables from the `.mat` file:

```python
from pathlib import Path
import numpy as np
import xarray as xr
from src.matlab import MATConverter

mat_path = Path("data/matlab/simulation_run.mat")

# 1. Initialize converter and open MATLAB Engine session
with MATConverter(mat_path) as converter:
    # 2. Read workspace variables as wrapped objects (MATStruct / CellArray)
    workspace = converter.read()
    sim_runs = workspace["sweep_data"]

    # 3. Assemble mapping dictionary
    mapping = {
        "attrs": {"title": "Centrifugal Pump Test", "institution": "PSAI"},
    }

    for i, run in enumerate(sim_runs):
        exp_name = f"run_{i+1:02d}"
        time_arr = np.array(run.time.values, dtype=np.float64)
        node_coords = np.array(run.mesh_coords.values, dtype=np.float64)  # (N, 3)

        mapping[exp_name] = {
            "attrs": {"RPM": float(run.rpm), "flow_rate": float(run.Q)},
            "time": time_arr,
            "variables": {
                # Experiment-level scalar signal
                "Power_Consumption": xr.DataArray(run.power_kW, dims=["time"], attrs={"units": "kW"}),
            },
            "volute": {
                "coordinates": node_coords,
                "variables": {
                    # Distributed transient spatial fields: shape (T, N)
                    "Pressure": xr.DataArray(run.p_field, dims=["time", "node"], attrs={"units": "Pa"}),
                    "Velocity_Mag": xr.DataArray(run.u_field, dims=["time", "node"], attrs={"units": "m/s"}),
                },
            },
        }

    # 4. Export to NetCDF-4
    output_nc = converter.to_netcdf4(mapping, output_path="output/simulation_run.nc")
    print(f"Exported NetCDF-4 to: {output_nc}")
```

---

### 3.2. Declarative Sweep Ingestion with `MATSweepConverter`

When simulation sweeps follow a regular struct-array format, `MATSweepConverter` eliminates boilerplate by using dot-notation path expressions:

```python
from src.matlab import MATSweepConverter

with MATSweepConverter("data/matlab/potato_dataset.mat") as sweep_conv:
    # Read raw workspace
    data = sweep_conv.read()
    nd_struct_array = data["ND"]

    # Define schema using path expressions evaluated on each element in ND
    mesh_schema = {
        "variables": {
            "Oven_Temperature": "s.tab[0, 0].sel(col='Var1')",
            "Temperature": "s.tab[0, 1].sel(col=cols_no_time)",
            "Water_Saturation": "s.tab[0, 2].sel(col=cols_no_time)",
        },
        "coordinates": "s.coords",
        "time": "s.tab[0, 0].sel(col='time')",
    }

    # Automatically validates coordinate invariance across all runs and builds NetCDF-4
    output_nc = sweep_conv.to_netcdf4_from_schema(
        mat_struct=nd_struct_array,
        mesh_schema=mesh_schema,
        output_path="output/potato_sweep.nc",
        single_mesh=True,       # Omits geometry sub-group, storing fields directly under run
        coord_atol=1e-8,        # Spatial coordinate tolerance across runs
    )
    print(f"Successfully converted sweep: {output_nc}")
```

---

## 4. Working with MATLAB Containers

To simplify interaction with native MATLAB structures, the package wraps engine outputs into Pythonic types:

### `MATStruct`
Wraps a MATLAB `struct`. Supports both dictionary key access and attribute syntax:
```python
struct_val = workspace["header"]
print(struct_val["author"])  # Dictionary lookup
print(struct_val.author)    # Attribute lookup
```

### `MATStructArray`
Wraps a 1D or 2D array of MATLAB structs with lazy evaluation. Data is only requested from the engine when an index is accessed:
```python
runs = workspace["sweep"]
first_run = runs[0]          # Evaluated on demand
runs.preload()               # Preload all elements into memory for batch iterations
```

### `CellArray`
Wraps a MATLAB `cell` array as an `np.ndarray` of `object` dtype, supporting 1D/2D linear indexing:
```python
cells = workspace["cell_data"]
item = cells[0, 2]
```

---

## 5. Metadata & Provenance Embedding

In accordance with [GEMINI.md](file:///home/bruno/Documents/PSAIFileHandler/GEMINI.md), all ingested datasets preserve provenance without data loss. Configuration files, solver logs, and tabular boundary condition schedules can be embedded directly into group attributes:

- **File Path**: `"metadata": "path/to/log.txt"` reads the entire file as a UTF-8 string and stores it in attributes keyed by its basename (`{"log.txt": "<contents>"}`).
- **String Text**: `"metadata": "raw configuration text"` stores `{"metadata.txt": "raw configuration text"}`.
- **Dictionary**: `"metadata": {"key": "val"}` serializes values to clean NetCDF-compatible types (JSON-encoded if complex).

---

## 6. Verification & Inspection

You can inspect the generated NetCDF-4 hierarchical structure using `xarray.open_datatree`:

```python
import xarray as xr

# Open the unified hierarchical dataset
tree = xr.open_datatree("output/simulation_run.nc", engine="h5netcdf")

# Print tree representation
print(tree)

# Access a specific geometry group under run 01
volute_ds = tree["/run_01/volute"].to_dataset()
print("Coordinates:", volute_ds.coordinates.shape)
print("Pressure field:", volute_ds.Pressure)
```
