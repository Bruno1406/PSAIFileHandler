# COMSOL Ingestion & NetCDF-4 Standardization Guide

The `src/comsol/` package standardizes COMSOL Multiphysics exports (`.txt`, `.csv`, `.vtu`) across both standard and transposed layouts into hierarchical, CF-1.8 compliant NetCDF-4 files (`xarray.DataTree`).

---

## 1. Overview & Capabilities

COMSOL simulation sweeps typically generate heterogeneous files where:
- Each file corresponds to a spatial component or subdomain (e.g. `Inlet`, `Outlet`, `Blades`).
- A single file contains multiple sweep experiments (e.g. varying $Q_{\text{in}}$, rotational speed, and dynamic time $t$).
- Headers embed expressions, physical units, step indices, and parameter values.

`ComsolConverter` automatically parses these exports, matches variables via canonical aliases or regex, separates continuous temporal coordinates from discrete experiments, and builds the unified three-tier NetCDF-4 structure (`Experiment -> Geometry -> Data`).

### Key Capabilities
- **Multi-Format Support**: Reads standard space/tab-delimited `.txt`, comma-delimited `.csv`, and VTK XML Unstructured Grids (`.vtu`) via PyVista.
- **Transposition Auto-Detection**: Automatically detects whether text/CSV files are node-major (standard) or expression-major (transposed).
- **Declarative `data_schema`**: Users define the target NetCDF-4 hierarchy and bind target variables to COMSOL expressions.
- **Native Vector Assembly**: Declaring `"velocity": ["u", "v"]` automatically stacks component fields into a `spatial` dimension `(node, spatial)` or `(time, node, spatial)`.
- **Automatic Units Harvesting**: Captures physical units directly from COMSOL expressions (e.g., `u (m/s)`, `p (Pa)`) and stores them in variable attributes.
- **Canonical Aliases & Overrides**: Bridges short symbols (`u`, `p`) and long VTU strings (`Velocity_field,_x_component`) seamlessly.

---

## 2. Quickstart Examples

### 2.1. Steady-State Parametric Sweep (MRF Study)

```python
from pathlib import Path
from src.comsol import ComsolConverter

# 1. Define declarative schema
data_schema = {
    # Non-spatial experiment-level variables
    "variables": {
        "Volumetric Flux": "Q_in",
        "Rotational Speed": "rot_rpm",
    },
    
    # Geometry subdomains
    "inlet": {
        "coordinates": ["x", "y"],
        "variables": {
            "velocity": ["u", "v"],  # Vector assembly: shape (node, spatial)
            "pressure": "p",         # Scalar field: shape (node)
        },
    },
}

converter = ComsolConverter(data_schema=data_schema)

# 2. Convert directly to NetCDF-4 (auto-detects format: txt, transposed txt, or vtu)
nc_path = converter.to_netcdf4(
    files={"inlet": "data/comsol/Pump2D_MRFStudy_UltraFine_Inlet.txt"},
    output_path="output/pump_mrf_study.nc",
)
print(f"Exported NetCDF-4 dataset to: {nc_path}")
```

---

### 2.2. Transient Dynamic Sweep (TRN Study)

In transient sweeps, specifying `"time": "Time"` tells the converter to treat `Time` as the continuous temporal coordinate ($T$), while remaining parameters define discrete experiments:

```python
import xarray as xr
from src.comsol import ComsolConverter

schema_trn = {
    "variables": {
        "Inflow": "Q_in",
        "RPM": "rot_rpm",
    },
    # Continuous temporal parameter
    "time": "Time",
    
    "static": {
        "coordinates": ["x", "y"],
        "variables": {
            "velocity": ["u", "v"],  # Transient vector: shape (time, node, spatial)
            "pressure": "p",         # Transient scalar: shape (time, node)
        },
    },
}

converter = ComsolConverter(data_schema=schema_trn)

# Convert to in-memory DataTree or export to NetCDF-4
dt = converter.to_datatree(
    files={"static": "data/comsol/Pump2D_TRN_Static_every5th.csv"}
)

# Access transient fields
first_run = list(dt.children.keys())[0]
static_ds = dt[f"{first_run}/static"].to_dataset()

print("Time coordinates:", static_ds.time.values)
print("Velocity field shape (time, node, spatial):", static_ds.velocity.shape)
print("Pressure field shape (time, node):", static_ds.pressure.shape)
```

---

### 2.3. Multi-Geometry Domain Decomposition

When a simulation study partitions the physical continuum across multiple files (e.g. `Inlet`, `Outlet`, `Blades`, `Main`):

```python
data_schema = {
    "variables": {"Flow": "Q_in", "RPM": "rot_rpm"},
    "inlet": {
        "coordinates": ["x", "y"],
        "variables": {"velocity": ["u", "v"], "pressure": "p"},
    },
    "outlet": {
        "coordinates": ["x", "y"],
        "variables": {"velocity": ["u", "v"], "pressure": "p"},
    },
    "blades": {
        "coordinates": ["x", "y"],
        "variables": {"velocity": ["u", "v"], "pressure": "p"},
    },
}

converter = ComsolConverter(data_schema=data_schema)

# Pass multiple files matching the geometry keys
converter.to_netcdf4(
    files={
        "inlet": "data/comsol/Pump2D_MRFStudy_UltraFine_Inlet.vtu",
        "outlet": "data/comsol/Pump2D_MRFStudy_UltraFine_Outlet.vtu",
        "blades": "data/comsol/Pump2D_MRFStudy_UltraFine_Blades.vtu",
    },
    output_path="output/pump_multi_domain.nc",
)
```

---

## 3. Data Schema Specification

The `data_schema` dictionary mirrors the NetCDF-4 tree hierarchy:

```text
/ (Root)
└── /{experiment_name}/          <-- Derived from exp_naming (default: run_001)
    ├── Top-level variables: Q_in, rot_rpm, time
    └── /{geometry_name}/        <-- Geometries defined in schema
        ├── coordinates: (node, spatial)
        └── Distributed fields: velocity, pressure, traction
```

### Schema Parameters
| Key | Type | Description |
| :--- | :--- | :--- |
| `"variables"` | `dict[str, str]` | Non-spatial experiment-level variables mapped to COMSOL parameter names (e.g. `{"Volumetric Flux": "Q_in"}`). |
| `"time"` | `str` \| `None` | Name of parameter representing physical simulation time (e.g. `"Time"` or `"t"`). If `None`, steady-state mode is assumed. |
| `"<geometry_name>"` | `dict` | Specification for a spatial subdomain matching a key in `files={...}`. |
| `"<geometry_name>"]["coordinates"]` | `list[str]` | Coordinate column names to extract (e.g. `["x", "y"]` or `["x", "y", "z"]`). |
| `"<geometry_name>"]["variables"]` | `dict[str, str \| list[str]]` | Target variable name mapped to a COMSOL expression string or component list. |

---

## 4. Field Aliases & Resolution

COMSOL exports vary between short symbols in text files (`u`, `p`) and descriptive names in VTU grids or solver logs (`Velocity_field,_x_component`, `Pressure`).

The alias resolution engine operates in two complementary, non-redundant tiers:

### 4.1. Fast-Path Dictionary: `DEFAULT_FIELD_ALIASES`
A static mapping of standard single-letter and CFD mathematical shorthands that provides immediate $O(1)$ lookup:
- **Navier-Stokes components**: `u` $\to$ `vx`, `v` $\to$ `vy`, `w` $\to$ `vz`
- **Coordinate-named velocity**: `x` $\to$ `vx`, `y` $\to$ `vy`, `z` $\to$ `vz`
- **Pressure**: `p` $\to$ `pressure`
- **Operators & canonical symbols**: `|u|` $\to$ `velocity_mag`, `alphat` $\to$ `alphat`, `t_tracx` $\to$ `t_tracx`

### 4.2. Dynamic Pattern Engine: `DEFAULT_REGEX_RULES`
A list of compiled regex patterns designed to match complex, multi-word descriptive phrases across punctuation styles (`_`, `,`, spaces) and automatically extract vector components:
- **Velocity components**: Matches `"Velocity_field,_x_component"`, `"Velocity field, y component"`, `"velocity x"`, `"u_comp1"` $\to$ `"vx"`, `"vy"`, `"vz"`.
- **Velocity magnitude**: Matches `"Velocity_field"`, `"Velocity magnitude"`, `"speed"` $\to$ `"velocity_mag"`.
- **Traction**: Matches `"Total_traction,_exterior_boundaries,_x_component"`, `"traction_x"` $\to$ `"t_tracx"`.
- **Pressure & Rotation**: Matches `"static_pressure"` $\to$ `"pressure"`, `"Rotation_angle"` $\to$ `"alphat"`.

Matches produced by `DEFAULT_REGEX_RULES` are dynamically cached into the active aliases dictionary so subsequent lookups for that variable during the simulation run are instant $O(1)$.

| Target Variable in Schema | Resolves In `.txt` / `.csv` | Resolves In `.vtu` / Long Forms |
| :--- | :--- | :--- |
| `"pressure": "p"` | `p (Pa)` | `Pressure_@_...`, `static_pressure` |
| `"velocity": ["u", "v"]` | `u (m/s)`, `v (m/s)` | `Velocity_field,_x_component`, `Velocity field, y component` |
| `"total_traction": ["t_tracx", "t_tracy"]` | `t_tracx`, `t_tracy` | `Total_traction,_exterior_boundaries,_x_component`, ... |
| `"rotation_angle": "alphat"` | `alphat` | `Rotation_angle_@_...` |

### 4.3. Custom Aliases Override
You can supply custom aliases when instantiating `ComsolConverter`, which strictly override any default dictionary or regex rule:
```python
converter = ComsolConverter(
    data_schema=data_schema,
    custom_aliases={"stress_xx": "spf.T_stressx", "p": "pressure_abs"},
)
```

---

## 5. Experiment Group Naming

By default, experiment groups are named sequentially using the template `run_{step:03d}` (e.g. `run_001`, `run_002`, ...).

You can supply a custom format string or callable:

```python
# Format string using parameter names
converter = ComsolConverter(
    data_schema=data_schema,
    exp_naming="sweep_Qin{Q_in}_rpm{rot_rpm}",
)

# Custom callable
def custom_naming(params: dict, step_idx: int) -> str:
    return f"exp_rpm_{int(params['rot_rpm'])}_q_{params['Q_in']}"

converter = ComsolConverter(
    data_schema=data_schema,
    exp_naming=custom_naming,
)
```

---

## 6. Compression & NetCDF-4 Export

All exported NetCDF-4 files generated by `converter.to_netcdf4()` comply with CF-1.8 and include:
- HDF5 deflate compression (`zlib=True`, `complevel=4`, `shuffle=True`).
- Chunking along the leading dimension (`time` for transient simulations, `node` for spatial meshes).
- Clean, zero-copy serialization compatible across `h5netcdf`, `netcdf4`, and `xarray.open_datatree`.
