# Specification 02: COMSOL Export Ingestion & NetCDF-4 Standardization

**Status:** Approved  
**Target Subsystem:** `src/comsol/`, `tests/`  
**Related Guidelines:** [GEMINI.md](file:///home/bruno/Documents/PSAIFileHandler/GEMINI.md)

---

## 1. Context & Motivation

COMSOL Multiphysics exports simulation data across diverse formats (`.txt`, `.csv`, `.vtu`), each potentially formatted as either standard (node-major) or transposed (expression-major). 

Unlike MATLAB sweep exports (where a single `.mat` file often groups multiple runs across all subdomains), COMSOL parametric sweeps export:
1. **One file per geometry subdomain** (e.g. `Pump2D_MRFStudy_UltraFine_Inlet.txt`, `Pump2D_MRFStudy_UltraFine_Blades.txt`).
2. **Multiple experiments combined within a single file** across parametric sweep combinations (e.g. varying $Q_{\text{in}}$, $\text{rot\_rpm}$, and dynamic simulation $t$).
3. **Embedded metadata in column headers / comments**, defining the variable expression, units, step index, and parameter values.

This specification formalizes the architecture, algorithms, and interface contracts for ingesting COMSOL exports into the unified CF-1.8 NetCDF-4 hierarchical format (`xarray.DataTree`) following the three-tier structure (`Experiment -> Geometry -> Data`).

---

## 2. Architectural Design & Module Breakdown

The subsystem is modularized under `src/comsol/` to separate low-level text/VTK parsing from high-level tree assembly:

```text
src/comsol/
├── __init__.py           # Public exports: ComsolConverter
├── header_parser.py      # Regex engine for step, parameter, unit, and expression extraction
├── parsers/
│   ├── __init__.py
│   ├── base.py           # Abstract BaseComsolParser interface
│   ├── flat_text.py      # FlatTextParser (standard space/comma-separated files)
│   ├── transposed_text.py# TransposedTextParser (transposed expression blocks)
│   └── vtu_parser.py     # VTUParser (VTK/PyVista unstructured grids)
└── converter.py          # ComsolConverter: multi-file coordinator & DataTree builder
```

---

## 3. Mathematical & Algorithmic Formulation

### 3.1. Header Parsing Syntax & Regex Extraction
In COMSOL exports, expression identifiers in column headers or comment lines follow the canonical pattern:
```text
{field_expr} [({units})] @ {step_index}: {param_1}={val_1} {unit_1}, {param_2}={val_2} {unit_2}, ...
```

In standard (non-transposed) text files, column boundary detection leverages the invariant that every expression column contains `@` (`@\s*(?P<step>\d+):`). The segment between consecutive `@` anchors delimits the parameters of step $i$ from the expression identifier of step $i+1$.

The header parser employs structured regular expressions:
```python
HEADER_REGEX = re.compile(
    r"^(?P<expr>.*?)\s*(?:\((?P<units>[^)]+)\))?\s*@\s*(?P<step>\d+):\s*(?P<params>.*)$"
)
PARAM_REGEX = re.compile(
    r"(?P<key>[a-zA-Z_0-9]+)\s*=\s*(?P<val>[-+]?[0-9]*\.?[0-9]+(?:[eE][-+]?[0-9]+)?)\s*(?P<unit>[^,;]*)"
)
```

- **Expression Extraction**: Extracts the raw variable name (e.g. `u`, `p`, `spf.T_stressx`).
- **Units Extraction**: Automatically captures units (e.g. `m/s`, `Pa`, `N/m^2`, `rpm`, `m^3/h`) and stores them directly in `attrs["units"]`.
- **Parameter Extraction**: Parses key-value-unit triplets for all swept parameters.

### 3.2. Canonical Field Aliases & VTU Normalization
To guarantee format parity across `.txt`, `.csv`, and `.vtu`, the parser resolves variable names against a canonical alias mapping:
```python
DEFAULT_FIELD_ALIASES = {
    "pressure": "pressure",
    "p": "pressure",
    "velocity_mag": "velocity_mag",
    "velocity_magnitude": "velocity_mag",
    "|u|": "velocity_mag",
    "speed": "velocity_mag",
    "velocity": "velocity_mag",
    "vx": "vx",
    "velocity_x": "vx",
    "v_x": "vx",
    "x": "vx",
    "u": "vx",
    "ux": "vx",
    "vy": "vy",
    "velocity_y": "vy",
    "v_y": "vy",
    "y": "vy",
    "v": "vy",
    "uy": "vy",
    "vz": "vz",
    "velocity_z": "vz",
    "v_z": "vz",
    "z": "vz",
    "w": "vz",
    "uz": "vz",
    "t_tracx": "t_tracx",
    "t_tracy": "t_tracy",
    "t_tracz": "t_tracz",
    "traction_x": "t_tracx",
    "traction_y": "t_tracy",
    "traction_z": "t_tracz",
    "alphat": "alphat",
    "rotation_angle": "alphat",
}
```
VTU descriptive names from `_RX_COMSOL_ARRAY` (e.g., `Velocity_field` with components `x, y, z`, `Total_traction,_exterior_boundaries`, and `Rotation_angle`) are automatically mapped to their canonical representations (`vx`, `vy`, `vz`, `t_tracx`, `alphat`). Users can supply `custom_field_aliases` to override or extend these definitions.

### 3.2. Disambiguation: Time Coordinate vs. Sweep Experiments
A critical algorithmic step is distinguishing between continuous temporal simulation coordinates and discrete experimental sweeps:

1. **If `"time"` is defined in `data_schema`** (e.g. `"time": "Time"` or `"t"`):
   - The parameter matching `"time"` is treated as the continuous 1D temporal dimension coordinate:
     $$\mathbf{t} = [t_0, t_1, \dots, t_{T-1}] \in \mathbb{R}^T \quad (\text{units: } \text{s})$$
   - All remaining parameters (e.g. $\text{rot\_rpm}, Q_{\text{in}}$) define the discrete experimental run. Steps with identical non-temporal parameters belong to the **same experiment** across time $T$.
   - Spatial fields are reshaped into transient arrays with shape $(T, N)$ or $(T, N, d)$, where `time` is the leading dimension.

2. **If `"time"` is not defined or `None`** (Steady-State Sweeps):
   - Each unique parameter combination (or step index) defines an independent static **experiment**.
   - Spatial fields have shape $(N)$ or $(N, d)$.

### 3.3. Vector Assembly & Dimensionality
When a variable in `data_schema` maps to a sequence of component expressions (e.g. `"velocity": ["u", "v"]` or `["u", "v", "w"]`):
- The parser matches and extracts each component array $\mathbf{v}_k \in \mathbb{R}^N$ (or $\mathbb{R}^{T \times N}$).
- It stacks components along a new `spatial` coordinate dimension:
  $$\mathbf{V} = [\mathbf{v}_1, \mathbf{v}_2, \dots, \mathbf{v}_d] \in \mathbb{R}^{N \times d} \quad \text{or} \quad \mathbb{R}^{T \times N \times d}$$
- The coordinate labels for `spatial` default to `['x', 'y']` for $d=2$ and `['x', 'y', 'z']` for $d=3$.

### 3.4. Spatial Discretization & Coordinate Invariance
Each geometry file must supply spatial node coordinates $\mathbf{X} \in \mathbb{R}^{N \times d}$.
- In flat text files: columns corresponding to `schema["coordinates"]` (e.g. `["x", "y"]`).
- In transposed files: rows labeled `% x`, `% y`.
- In VTU files: `mesh.points[:, :d]`.

For any geometry, mesh coordinates $\mathbf{X}$ must remain invariant across all sweep steps:
$$\max_{i, j} \left| X_{ij}^{(e)} - X_{ij}^{(1)} \right| \le 10^{-8}$$

---

## 4. `data_schema` Specification

The user provides a declarative `data_schema` dictionary specifying the desired NetCDF-4 tree layout:

```python
data_schema = {
    # 1. Experiment-level scalar inputs / sweep parameters
    "variables": {
        "Volumetric Flux": "Q_in",
        "Rotational Speed": "rot_rpm",
    },
    
    # 2. Continuous time parameter (set to None for steady-state)
    "time": "Time",  # or "t"

    # 3. Geometry domains (keys match the geometry keys passed in files={...})
    "inlet": {
        "coordinates": ["x", "y"],
        "variables": {
            "velocity": ["u", "v"],
            "pressure": "p",
            "total_traction": ["spf.T_stressx", "spf.T_stressy"],
        },
    },
    "blades": {
        "coordinates": ["x", "y"],
        "variables": {
            "velocity": ["u", "v"],
            "pressure": "p",
        },
    },
}
```

---

## 5. Interface Contracts & Signatures

### 5.1. `ComsolConverter`
High-level coordinator class:

```python
class ComsolConverter:
    def __init__(
        self,
        data_schema: dict[str, Any],
        exp_naming: str | Callable[[dict[str, Any], int], str] | None = "run_{step:03d}",
    ) -> None:
        """Initialize the COMSOL converter with a target schema.
        
        Parameters
        ----------
        data_schema : dict[str, Any]
            Specification mapping experiment parameters and geometry fields.
        exp_naming : str | Callable | None
            Naming template for experiment groups. Defaults to 'run_{step:03d}'.
            Available template keys: {step}, {index}, plus any parameter key (e.g. {Q_in}, {rot_rpm}).
        """
        ...

    def to_datatree(
        self,
        files: dict[str, str | Path],
        transposed: dict[str, bool] | bool | None = None,
    ) -> xr.DataTree:
        """Parse geometry files and construct an xarray.DataTree."""
        ...

    def to_netcdf4(
        self,
        files: dict[str, str | Path],
        output_path: str | Path,
        transposed: dict[str, bool] | bool | None = None,
        complevel: int = 4,
        shuffle: bool = True,
    ) -> Path:
        """Convert geometry files and export directly to a NetCDF-4 file."""
        ...
```

### 5.2. File Parser Interface (`BaseComsolParser`)
All file format parsers implement a common contract:

```python
class BaseComsolParser(ABC):
    @abstractmethod
    def get_coordinates(self, coord_names: list[str]) -> np.ndarray:
        """Return (N, d) coordinates array."""
        ...

    @abstractmethod
    def parse_expressions(
        self,
        target_patterns: dict[str, str | list[str]],
        time_param: str | None,
    ) -> ParsedComsolData:
        """Extract matched expression data, parameters, and time steps."""
        ...
```

---

## 6. Auto-Detection Mechanics

1. **File Type Detection**:
   - Inferred from file suffix: `.txt`, `.csv`, `.vtu`.
2. **Transposition Auto-Detection (for text/csv files)**:
   - Scans the first 15 lines of the file.
   - If line 9+ contains a single coordinate label per line (`% x` followed on the next line by $N$ numerical tokens), set `transpose=True`.
   - If line 9 contains multiple column headers (`% x y u (m/s) ...` or `% x,y,u (m/s) ...`), set `transpose=False`.
   - Explicit user override (`transposed=True/False`) takes precedence.

---

## 7. Testing & Validation Strategy

### 7.1. Benchmark Fixtures
Unit tests will run on lightweight, fast fixtures:
- **Steady-State MRF**: `data/comsol/Pump2D_MRFStudy_UltraFine_Inlet.{txt, vtu, Transpose.txt}` (~2.1 MB each).
- **Transient TRN**: `data/comsol/Pump2D_TRN_Static_every5th_Transpose_only3stepsForDemo.csv` (99 KB).

### 7.2. Acceptance Criteria
1. **Format Parity**:
   Ingesting `Pump2D_MRFStudy_UltraFine_Inlet.txt`, `Inlet_Transpose.txt`, and `Inlet.vtu` with the same `data_schema` must yield numerically identical DataTree structures:
   $$\max |A_{\text{txt}} - A_{\text{transposed}}| \le 10^{-5}, \quad \max |A_{\text{txt}} - A_{\text{vtu}}| \le 10^{-5}$$
2. **Dimension Compliance**:
   - Experiment-level variables: strictly no `node` dimension.
   - Geometry-level variables: strict adherence to `(node)`, `(node, spatial)`, `(time, node)`, or `(time, node, spatial)`.
3. **CF-1.8 & NetCDF-4 Engine Compatibility**:
   Generated `.nc` files must open seamlessly via `xarray.open_datatree(engine="h5netcdf")` and `netCDF4.Dataset`.
