# Repository Refactoring: PSAIFileHandler Architecture Documentation

This document records the architectural reorganization and baseline standardization of the repository, transitioning from `PSAIMiddleware` to `PSAIFileHandler`. It formalizes module boundaries across simulation providers (COMSOL, OpenFOAM, MATLAB) and establishes dependency declarations and project hierarchies in accordance with [GEMINI.md](file:///home/bruno/Documents/PSAIMiddleware/GEMINI.md).

## Executive Summary

1. **Repository Identity & Renaming**: Renamed the project identity from `PSAIMiddleware` to `PSAIFileHandler` across configuration and metadata files ([`pyproject.toml`](file:///home/bruno/Documents/PSAIMiddleware/pyproject.toml), [`README.md`](file:///home/bruno/Documents/PSAIMiddleware/README.md)).
2. **Package Modularization**: Deprecated and removed the legacy `src/file_handler/` directory, distributing domain-specific loaders into dedicated packages:
   - [`src/comsol/`](file:///home/bruno/Documents/PSAIMiddleware/src/comsol/): Ingestion, tabular parsing, VTU unstructured grid extraction, and canonical naming.
   - [`src/matlab/`](file:///home/bruno/Documents/PSAIMiddleware/src/matlab/): Handling of MATLAB `.mat` containers, nested structs, cell arrays, and serialization to hierarchical NetCDF-4/HDF5.
   - [`src/openfoam/`](file:///home/bruno/Documents/PSAIMiddleware/src/openfoam/): Interfaces for OpenFOAM polyMesh parsing, field reconstruction, and PyFoam integration.
3. **Dependency Consolidation**: Updated [`pyproject.toml`](file:///home/bruno/Documents/PSAIMiddleware/pyproject.toml) to include all core numerical, IO, and simulation dependencies (`numpy`, `scipy`, `pandas`, `xarray`, `netcdf4`, `h5netcdf`, `h5py`, `pyvista`, `PyFoam`, `tqdm`, `matplotlib`, `jupyter`, `ipykernel`).
4. **Specification & Documentation Governance**: Initialized top-level [`specs/`](file:///home/bruno/Documents/PSAIMiddleware/specs/) and [`docs/`](file:///home/bruno/Documents/PSAIMiddleware/docs/) directories to adhere strictly to spec-driven development rules.

---

## 1. COMSOL Module (`src/comsol/`)

**Location:** [`src/comsol/comsol.py`](file:///home/bruno/Documents/PSAIMiddleware/src/comsol/comsol.py)

### Mathematical & Physical Formulation
COMSOL exports spatial field evaluations over discrete meshes $\Omega \subset \mathbb{R}^d$ ($d \in \{2, 3\}$). For node coordinates $\mathbf{x}_i = (x_i, y_i, z_i) \in \mathbb{R}^3$, scalar fields $p(\mathbf{x}_i)$ and vector velocity fields $\mathbf{u}(\mathbf{x}_i) = (u_{x,i}, u_{y,i}, u_{z,i})$ satisfy:
$$|\mathbf{u}_i| = \sqrt{u_{x,i}^2 + u_{y,i}^2 + u_{z,i}^2}$$
Field variables are mapped to canonical representations to guarantee cross-solver invariance across COMSOL table outputs and VTU datasets.

### Implementation Rationale & Architectural Decisions
- Removed monolithic `file_handler` packaging in favor of domain-scoped subpackages.
- Preserved alias dictionary `CANONICAL_FIELD_ALIASES` mapping pressure, velocity components, traction forces, and rotation angles into consistent variable identifiers.
- Prepared handlers for both tabular text exports (transposed and non-transposed) and VTK/VTU mesh series.

### Core Reference Snippets
```python
class ComsolFileHandler:
    def __init__(
        self,
        file_path: Path,
        transpose: bool = True,
        canonical: bool = True,
        parameters: list[str] | None = None,
        fields: list[str] | None = None,
    ) -> None:
        self.file_path = Path(file_path)
        self.transpose = transpose
        self.canonical = canonical
        self.extension = "".join(self.file_path.suffixes)
        self.parameters = parameters
        self.fields = fields
        self.data = self._read_file()
```

---

## 2. MATLAB Converter Module (`src/matlab/`)

**Location:** [`src/matlab/mat_to_netcdf4.py`](file:///home/bruno/Documents/PSAIMiddleware/src/matlab/mat_to_netcdf4.py)

### Mathematical & Physical Formulation
MATLAB structures encode hierarchical experiment records containing temporal trajectories $t \in [0, T]$, driving thermal boundary conditions $T_{\text{oven}}(t)$, localized sensor points $\mathbf{x}_{\text{probe}} \in \mathbb{R}^3$, and full 3D spatial temperature fields $T(\mathbf{x}_j, t)$ across $N$ tetrahedral mesh vertices.
Converters map these structures into the standard CF-compliant hierarchy:
$$\mathcal{T}_{\text{root}} \rightarrow \mathcal{G}_{\text{experiment}} \rightarrow \mathcal{G}_{\text{geometry}} \rightarrow \mathbf{V}(\text{time}, \text{node})$$

### Implementation Rationale & Architectural Decisions
- Encapsulated `CellArray` (inheriting from `np.ndarray`) and `MATStruct` (implementing `Mapping[str, Any]`) to emulate MATLAB semantics without requiring external runtimes during parsing of pre-extracted records.
- Standardized group generation using `xarray.DataTree` and `h5netcdf` / `netcdf4` storage engines with deflate compression (`complevel=4`, `shuffle=True`).

### Core Reference Snippets
```python
class MATStruct(Mapping[str, Any]):
    def __init__(self, fields: dict[str, Any]) -> None:
        self.__dict__["_fields"] = fields

    def __getitem__(self, key: str) -> Any:
        if key in self._fields:
            return self._fields[key]
        raise KeyError(f"Field '{key}' not found in struct.")
```

---

## 3. OpenFOAM Module (`src/openfoam/`)

**Location:** [`src/openfoam/__init__.py`](file:///home/bruno/Documents/PSAIMiddleware/src/openfoam/__init__.py)

### Mathematical & Physical Formulation
OpenFOAM represents polyhedral finite volume discretizations with cell-centered and boundary patch values. Field transformations convert cell and patch values to node-interpolated coordinates $(x_i, y_i, z_i)$ or preserve native polyhedral connectivity for CF-compliant export.

### Implementation Rationale & Architectural Decisions
- Dedicated package namespace `src/openfoam/` prepared for case parsers, boundary condition schedule injectors, and PyFoam execution runners.
- Ensures isolation between finite element (COMSOL), finite volume (OpenFOAM), and lumped/experimental (MATLAB) workflows.

---

## Integration & Verification

### Verification of Directory Structure
```bash
ls -la src/
# Expected:
# comsol/
# matlab/
# openfoam/
```

### Module Import Validation
```python
from src.comsol import ComsolFileHandler
from src.matlab import CellArray, MATStruct, mat_to_netcdf4
import src.openfoam
```
