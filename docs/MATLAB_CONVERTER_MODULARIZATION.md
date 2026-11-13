# MATLAB Converter Modularization Documentation

This document records the modularization and object-oriented restructuring of the MATLAB ingestion and NetCDF-4 standardization subsystem in `PSAIFileHandler` according to [specs/01_matlab_converter_modularization.md](file:///home/bruno/Documents/PSAIFileHandler/specs/01_matlab_converter_modularization.md) and [GEMINI.md](file:///home/bruno/Documents/PSAIFileHandler/GEMINI.md).

## Executive Summary

1. **Monolithic Script Elimination**: Decommissioned `mat_to_netcdf4.py` without backward-compatibility shims, per early-stage development guidelines.
2. **Modular Architecture**: Distributed MATLAB ingestion into five focused modules under [`src/matlab/`](file:///home/bruno/Documents/PSAIFileHandler/src/matlab/):
   - `containers.py`: Low-level MATLAB type emulation (`CellArray`, `MATStruct`, `MATStructArray`, `deserialize_matlab_value`).
   - `mat_file.py`: Engine lifecycle and workspace management (`MATFile`).
   - `accessors.py`: Declarative AST path parsing and evaluation (`PathAccessor`).
   - `converter.py`: General NetCDF-4/DataTree conversion class (`MATConverter`).
   - `sweep_converter.py`: Declarative sweep converter (`MATSweepConverter`) using composition with facade forwarding.
3. **Invariance Tolerance**: Updated coordinate invariance checks to use `np.allclose` with configurable tolerance `coord_atol=1e-8`.
4. **Test Suite Isolation**: Relocated dataset-specific converters and verification routines into [`tests/test_chicken_dataset.py`](file:///home/bruno/Documents/PSAIFileHandler/tests/test_chicken_dataset.py) and [`tests/test_potato_dataset.py`](file:///home/bruno/Documents/PSAIFileHandler/tests/test_potato_dataset.py).

---

## 1. Containers & Deserialization (`src/matlab/containers.py`)

**Location:** [`src/matlab/containers.py`](file:///home/bruno/Documents/PSAIFileHandler/src/matlab/containers.py)

### Mathematical & Physical Formulation
MATLAB struct arrays and cell arrays store heterogeneous physical data arrays with column-major ordering. For a multi-dimensional array with shape $(S_1, S_2, \dots, S_d)$, linear indexing follows:
$$\text{index}_{\text{MATLAB}} = 1 + \sum_{k=1}^d \left( i_k \prod_{m=1}^{k-1} S_m \right)$$
`CellArray` and `MATStructArray` maintain this indexing logic during lazy evaluation over the MATLAB engine.

### Implementation Rationale & Architectural Decisions
- `CellArray`: Inherits from `np.ndarray` with `dtype=object` to preserve MATLAB cell array geometry while supporting linear indexing for $1 \times N$ or $N \times 1$ vectors.
- `MATStruct`: Implements `Mapping[str, Any]` and custom `__getattr__` for intuitive attribute (`s.val`) and dictionary access.
- `MATStructArray`: Implements `Sequence[MATStruct]` with lazy caching, avoiding the upfront overhead of evaluating large simulation datasets in memory.

### Core Reference Snippets
```python
class MATStruct(Mapping[str, Any]):
    def __init__(self, fields: dict[str, Any]) -> None:
        self.__dict__["_fields"] = fields

    def __getattr__(self, name: str) -> Any:
        if name in self._fields:
            return self._fields[name]
        raise AttributeError(f"Struct has no field '{name}'.")
```

---

## 2. Engine Lifecycle & Workspace Reader (`src/matlab/mat_file.py`)

**Location:** [`src/matlab/mat_file.py`](file:///home/bruno/Documents/PSAIFileHandler/src/matlab/mat_file.py)

### Implementation Rationale & Architectural Decisions
- Strict reliance on `matlab.engine` per user requirement (no fallbacks to `scipy.io.loadmat` or `h5py` due to modern nested MATLAB struct references).
- Employs context manager lifecycle (`__enter__`, `__exit__`) to guarantee that MATLAB engine processes are closed cleanly upon task completion.

---

## 3. General Converter Class (`src/matlab/converter.py`)

**Location:** [`src/matlab/converter.py`](file:///home/bruno/Documents/PSAIFileHandler/src/matlab/converter.py)

### Implementation Rationale & Architectural Decisions
- `MATConverter` encapsulates a `MATFile` instance (`self.mat_file`).
- Normalizes variable dimensions into standard simulation dimensions:
  - Temporal scalar inputs: `(time)`
  - Static spatial fields: `(node)` or `(node, spatial)`
  - Transient spatial fields: `(time, node)` or `(time, node, spatial)`
- Serializes hierarchy trees into CF-1.8 compliant NetCDF-4 using `h5netcdf` engine with deflate compression.

### Core Reference Snippets
```python
class MATConverter:
    def __init__(self, mat_file_or_path: MATFile | str | Path, **kwargs: Any) -> None:
        if isinstance(mat_file_or_path, MATFile):
            self.mat_file = mat_file_or_path
        else:
            self.mat_file = MATFile(mat_file_or_path, **kwargs)

    def to_netcdf4(self, mapping: dict[str, Any], output_path: str | Path, ...) -> Path:
        return mat_to_netcdf4(mapping, output_path=output_path, ...)
```

---

## 4. Structured Sweep Converter (`src/matlab/sweep_converter.py`)

**Location:** [`src/matlab/sweep_converter.py`](file:///home/bruno/Documents/PSAIFileHandler/src/matlab/sweep_converter.py)

### Mathematical & Physical Formulation
In parametric simulation sweeps, spatial discretization coordinates $\mathbf{X} \in \mathbb{R}^{N \times d}$ must satisfy coordinate invariance across all experimental runs $e \in \{1, \dots, E\}$:
$$\max_{i, j} \left| X_{ij}^{(e)} - X_{ij}^{(1)} \right| \le \varepsilon_{\text{atol}} \quad (\varepsilon_{\text{atol}} = 10^{-8})$$
The invariance validator evaluates this condition across all sweep iterations using `np.allclose`.

### Implementation Rationale & Architectural Decisions
- Uses **Composition with Convenience Facade Forwarding**: `MATSweepConverter` owns an instance of `MATConverter`.
- Users define declarative schemas via `PathAccessor` strings (e.g. `'s.info.headers[0]'`) to automatically compile hierarchical mapping dictionaries without writing procedural iteration loops.

---

## 5. Integration & Verification

### Validation Loop & Ground Truth Benchmarks
Both dataset converters were executed in a comprehensive validation loop against the reference NetCDF files stored in [`data/matlab/`](file:///home/bruno/Documents/PSAIFileHandler/data/matlab/):
- **Chicken Dataset Benchmark:** Generated output validated against [`data/matlab/chicken_dataset.nc`](file:///home/bruno/Documents/PSAIFileHandler/data/matlab/chicken_dataset.nc). Verified exact group hierarchy (`all_probes_measurements`, `single_probe_measurements`), temporal array dimensions, probe coordinates, and physical variable parity.
- **Potato Dataset Benchmark:** Generated output validated against [`data/matlab/potato_dataset.nc`](file:///home/bruno/Documents/PSAIFileHandler/data/matlab/potato_dataset.nc). Verified exact coordinate arrays, 4,649-node spatial meshes, and variable parity across runs (`Temperature`, `Water Saturation`, `Oven Temperature`).

### Running the Test Suite
```bash
# Execute full pytest suite with reference comparison
~/.local/bin/uv run pytest tests/ -s
```
