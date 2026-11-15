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
- **Shorthand Auto-Discovery**: Pass simple lists of `geometries`, `variables`, and `parameters` without manually constructing complex schemas.
- **Declarative `data_schema`**: Full control to define the target NetCDF-4 hierarchy and bind target variables to COMSOL expressions.
- **Native Vector Assembly**: Declaring or discovering velocity components `["u", "v"]` automatically stacks them into a `spatial` dimension `(node, spatial)` or `(time, node, spatial)`.
- **Automatic Units Harvesting**: Captures physical units directly from COMSOL expressions (e.g., `u (m/s)`, `p (Pa)`) and stores them in variable attributes.
- **Canonical Aliases & Overrides**: Bridges short symbols (`u`, `p`) and long VTU strings (`Velocity_field,_x_component`) seamlessly.
- **Real-Time Progress Indication**: Built-in `tqdm` progress bars display geometry parsing and group assembly progress in real time.

---

## 2. Quickstart Examples

### 2.1. Zero-Boilerplate Shorthand API (Auto-Discovery)

When you do not want to write a full `data_schema`, simply pass a list of geometry domain names. The converter automatically inspects the input files, identifies spatial coordinates, matches canonical variable aliases, combines vector components (e.g. `u` and `v` into `velocity`), preserves raw names for unrecognized expressions (e.g. `spf.T_stressx`), and extracts sweep parameters into experiment-level variables:

```python
from psaifilehandler import ComsolConverter

# 1. Instantiate converter with geometry names and optional root attributes
converter = ComsolConverter(
    geometries=["pump", "blades", "inlet", "outlet"],
    attributes={
        "institution": "TU Darmstadt",
        "author": "Bruno Machado",
        "study": "Ultra-Fine MRF Sweep",
    },
    # Optional: parameters=["Q_in", "rot_rpm"]  # or custom aliases
    # Optional: variables=["pressure", "velocity"]  # selective filter
)

# 2. Convert directly to NetCDF-4 passing a list of files matching `geometries`
converter.to_netcdf4(
    files=[
        "Pump2D_MRFStudy_UltraFine_Main.txt",
        "Pump2D_MRFStudy_UltraFine_Blades.txt",
        "Pump2D_MRFStudy_UltraFine_Inlet.txt",
        "Pump2D_MRFStudy_UltraFine_Outlet.txt",
    ],
    output_path="pump_dataset.nc",
)
```

> [!TIP]
> - `attributes`: A dictionary of top-level global attributes written to the NetCDF-4 root group when `data_schema` is not set.
> - If `geometries` is omitted or empty, domains default to `["geometry_1", "geometry_2", ...]`.
> - The length of `geometries` must strictly equal the number of files passed.
> - `time_param` is **never** auto-discovered: steady-state is the safe default unless `time_param="Time"` is explicitly passed.
> - If an explicit `data_schema` is supplied, it takes strict priority over shorthand arguments (such as `geometries`, `variables`, `parameters`, `attributes`, and `time_param`).

---

### 2.2. Steady-State Parametric Sweep with Declarative Schema

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
│  Attributes: title, source, conventions="CF-1.8", institution, ...
│
└── /{experiment_name}/          <-- Derived from exp_naming (default: run_001)
    ├── Top-level variables: Q_in, rot_rpm, time
    └── /{geometry_name}/        <-- Geometries defined in schema
        ├── coordinates: (node, spatial)
        └── Distributed fields: velocity, pressure, traction
```

### 3.1. Example Schema with Global Metadata & Subdomains

```python
data_schema = {
    # Global dataset metadata (Root attributes)
    "title": "2D Centrifugal Pump Impeller & Volute Parameter Study",
    "source": "COMSOL Multiphysics 6.0",
    "attr": {
        "institution": "TU Darmstadt",
        "author": "Bruno Machado",
        "operating_condition": "Nominal design point",
    },
    
    # Non-spatial experiment-level variables
    "variables": {
        "Volumetric Flow": "Q_in",
        "Rotational Speed": "rot_rpm",
    },
    
    # Temporal coordinate (omit or set to None for steady-state)
    "time": "Time",
    
    # Geometry subdomains (non-reserved dictionary keys)
    "volute": {
        "coordinates": ["x", "y"],
        "variables": {
            "pressure": "p",
            "velocity": ["u", "v"],
        },
    },
    "impeller": {
        "coordinates": ["x", "y"],
        "variables": {
            "pressure": "p",
            "velocity": ["u", "v"],
        },
    },
}
```

### 3.2. Reserved Configuration Keys vs Geometry Domains

> [!IMPORTANT]
> At the top level of `data_schema`, keys are partitioned into **Reserved Configuration Keys** and **Geometry Subdomains**. You cannot name a spatial geometry domain using any of the reserved configuration names.

| Key Category | Key Name | Type | Description |
| :--- | :--- | :--- | :--- |
| **Root Metadata** | `"title"` | `str` | Custom dataset title (default: `"COMSOL Parametric Simulation Dataset"`). |
| **Root Metadata** | `"source"` | `str` | Simulation software or provenance tool (default: `"COMSOL Multiphysics"`). |
| **Root Metadata** | `"attr"` or `"attrs"` | `dict` | Dictionary of user-defined attributes attached to the NetCDF-4 root group (e.g. `institution`, `experiment_id`, `contact`). (Also accepts `"metadata"` / `"root_attrs"`). |
| **Driving Signals** | `"variables"` | `dict[str, str]` | Maps clean variable names to COMSOL parameter names without spatial dimensions (e.g. `{"Flow Rate": "Q_in"}`). |
| **Temporal Coordinate** | `"time"` | `str` \| `None` | Name of parameter representing simulation time (e.g. `"Time"` or `"t"`). If omitted or `None`, steady-state mode is assumed. |
| **Geometry Domains** | `"<geometry_name>"` | `dict` | Any non-reserved dictionary key defining a spatial domain (e.g. `"volute"`, `"inlet"`, `"outlet"`). Must contain `"coordinates"` and `"variables"`. |

### 3.3. Geometry Domain Specification

Within each `<geometry_name>` block:
- **`"coordinates"`** (`list[str]`): The spatial Cartesian coordinates to extract (e.g. `["x", "y"]` or `["x", "y", "z"]`).
- **`"variables"`** (`dict[str, str | list[str]]`): Target variable name mapped to a single scalar expression (e.g. `"pressure": "p"`) or a list of components stacked into vectors (e.g. `"velocity": ["u", "v"]`).

---

## 4. Field & Parameter Aliases

COMSOL exports heterogeneous expressions ranging from standard CFD shorthands (`u`, `v`, `p`) to physics-specific names (`spf.T_stressx`, `rot1.alpha`) and descriptive VTU arrays (`Velocity_field,_x_component`).

### 4.1. Default Field Aliases
The built-in fast-path dictionary maps standard expressions to clean canonical names:

| Raw Expression in File | Canonical Alias Name | Physical Meaning / Field Type |
| :--- | :--- | :--- |
| `p`, `pressure`, `static_pressure` | `pressure` | Static Pressure [Pa] |
| `u`, `vx`, `ux`, `x` | `vx` | Velocity x-component [m/s] |
| `v`, `vy`, `uy`, `y` | `vy` | Velocity y-component [m/s] |
| `w`, `vz`, `uz`, `z` | `vz` | Velocity z-component [m/s] |
| `\|u\|`, `speed`, `velocity_magnitude` | `velocity_mag` | Velocity magnitude [m/s] |
| `t_tracx`, `t_tracy`, `t_tracz` | `t_trac{x,y,z}` | Total traction components [N/m²] |
| `alphat`, `rotation_angle` | `alphat` | Impeller rotation angle [rad] |

### 4.1. The `variables` Mini-Schema (Spatial Fields & Vectors)
When `data_schema` is omitted, the `variables` argument acts as a geometry-agnostic mini-schema defining tensor structures and scalar field targets across all subdomains:

```python
variables = {
    # 2D/3D Vector fields: components are stacked into shape (node, spatial)
    "velocity": ["u", "v"],
    "total_traction": ["spf.T_stressx", "spf.T_stressy"],
    # Renamed scalar fields
    "rotation_angle": "rot1.alpha",
}
```

- **Automatic Multi-Domain Handling**: If a variable or vector (e.g. `total_traction`) is only present in one subdomain file (e.g. `blades`) and absent in others (`inlet`, `outlet`), the converter extracts it for `blades` and silently skips it for the other geometries without raising an error.
- **Raw Literal Preservation for Unmentioned Fields**: Any expression present in a COMSOL file that is **not** claimed by `variables` is automatically extracted as an individual 1D scalar using its exact raw name (e.g. `p (node)`).
- **Default (No variables passed)**: If `variables=None`, every field is extracted as an individual 1D scalar using its raw expression name.

### 4.2. The `parameters` Argument (Sweep Parameters)
Top-level non-spatial simulation sweep parameters (e.g. `Q_in`, `rot_rpm`) can be renamed cleanly via `parameters`:

```python
parameters = {
    "Volumetric Flow": "Q_in",
    "Rotational Speed": "rot_rpm",
}
```
Any sweep parameter not mentioned in `parameters` is automatically stored at the experiment level with its exact raw header name.

### 4.3. `custom_aliases` as a Vocabulary Bridge
The `custom_aliases` dictionary serves strictly as a **1-to-1 synonym bridge** between raw solver column headers and the identifiers declared in `variables` or `parameters`:

```python
converter = ComsolConverter(
    geometries=["pump", "blades"],
    custom_aliases={
        # Solver-specific raw headers mapped to standard identifiers
        "Comp1.u_x": "u",
        "Comp1.u_y": "v",
    },
    variables={
        # Variables mini-schema looks for 'u' and 'v', bridged by custom_aliases
        "velocity": ["u", "v"],
        "total_traction": ["spf.T_stressx", "spf.T_stressy"],
    },
    parameters={
        "flow": "Q_in",
        "rpm": "rot_rpm",
    },
)
```

In the resulting NetCDF-4 file:
- `/{run_name}/flow` contains the driving flow rate.
- `/{run_name}/rpm` contains the rotor speed.
- `/{run_name}/blades/velocity` is a 2D vector `(node, spatial)` assembled from `[Comp1.u_x, Comp1.u_y]`.
- `/{run_name}/blades/total_traction` is a 2D vector `(node, spatial)` assembled from `[spf.T_stressx, spf.T_stressy]`.
- Unmentioned fields (e.g. `p`, `w`) remain available as 1D scalar arrays with their exact raw names.

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
