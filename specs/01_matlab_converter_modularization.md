# Specification 01: Modularization of MATLAB File Handlers & Converters

**Status:** Implemented  
**Target Subsystem:** `src/matlab/`, `tests/`  
**Related Guidelines:** [GEMINI.md](file:///home/bruno/Documents/PSAIFileHandler/GEMINI.md)

---

## 1. Context & Motivation

The original prototype `mat_to_netcdf4.py` was a monolithic ~1,300-line script combining:
1. Low-level container emulation (`CellArray`, `MATStruct`, `MATStructArray`).
2. MATLAB Engine lifecycle and workspace reading (`MATFile`).
3. Declarative AST expression path evaluation (`PathAccessor`).
4. General mapping normalization, DataTree assembly, and NetCDF-4 export (`mat_to_netcdf4`).
5. Sweep mapping validation and declarative schema resolution (`build_structured_sweep_mapping`).
6. One-off dataset converter routines (`convert_chicken_dataset`, `convert_potato_dataset`) and ad-hoc verification in `__main__`.

In accordance with [GEMINI.md](file:///home/bruno/Documents/PSAIFileHandler/GEMINI.md), early-stage development allows clean, unencumbered refactoring without backward-compatibility shims. `mat_to_netcdf4.py` has been completely decommissioned and modularized.

---

## 2. Architectural Design & Module Breakdown

The subsystem is modularized into five focused library modules under `src/matlab/` and a standalone test suite in `tests/`:

```text
src/matlab/
├── __init__.py           # Unified public API exports
├── containers.py         # CellArray, MATStruct, MATStructArray, deserialization helpers
├── mat_file.py           # MATFile wrapper, engine lifecycle, workspace reader
├── accessors.py          # PathAccessor, compile_accessor, evaluate_accessor
├── converter.py          # MATConverter class (HAS a MATFile), NetCDF-4/DataTree exporter
└── sweep_converter.py    # MATSweepConverter class (composition, structured sweep schemas)

tests/
├── __init__.py
├── test_chicken_dataset.py  # Chicken dataset test case and verification (MATConverter)
└── test_potato_dataset.py   # Potato dataset test case and verification (MATSweepConverter)
```

---

## 3. Class Design & Module Specifications

### 3.1. `src/matlab/containers.py`
- `CellArray(np.ndarray)`: Preserves MATLAB cell array nesting and 1D/2D linear indexing fallback.
- `MATStruct(Mapping[str, Any])`: Dictionary wrapper allowing dual attribute (`s.val`) and key (`s["val"]`) access.
- `MATStructArray(Sequence[MATStruct])`: Sequence wrapper supporting lazy evaluation of large struct arrays over the MATLAB engine with `.preload()`.
- `deserialize_matlab_value(val: Any)`: Recursive converter from MATLAB engine types into standard Python/NumPy objects.

### 3.2. `src/matlab/mat_file.py`
- `MATFile`: Context manager managing `matlab.engine.start_matlab()`, license paths, workspace reflection (`who`, `class`, `size`), and cleanup on exit (`close()`). Strict requirement for `matlab.engine` per user specification.

### 3.3. `src/matlab/accessors.py`
- `PathAccessor`: Compiles and executes path expressions (e.g. `s.info.headers[0]`) against nested structs.
- `compile_accessor(val)` & `evaluate_accessor(accessor, root_obj)`: Safe evaluation utilities.

### 3.4. `src/matlab/converter.py` (`MATConverter`)
- **Relationship**: **HAS A** `MATFile` instance (`self.mat_file: MATFile`).
- **Class Definition**:
  ```python
  class MATConverter:
      mat_file: MATFile

      def __init__(self, mat_file_or_path: MATFile | str | Path, **kwargs: Any) -> None:
          ...

      def read(self, preload: bool = False, max_elements: int | None = None) -> dict[str, Any]:
          ...

      def build_datatree(self, mapping: dict[str, Any], ...) -> xr.DataTree:
          ...

      def to_netcdf4(self, mapping: dict[str, Any], output_path: str | Path, ...) -> Path:
          ...
  ```

### 3.5. `src/matlab/sweep_converter.py` (`MATSweepConverter`)
- **Relationship**: **Composition with convenience facade forwarding**.
- `self.converter = MATConverter(...)`
- `self.mat_file = self.converter.mat_file`
- Methods:
  - `build_sweep_mapping(mat_struct, mesh_schema, ...)`
  - `convert(mat_struct, mesh_schema, output_path, ...)`
  - `_validate_sweep_invariance(...)`: Uses `np.allclose(coord_a, coord_b, atol=coord_atol)` for numerical tolerance on coordinates.
  - Facade forwarding: `to_netcdf4`, `build_datatree`, `read`, context manager protocol.

---

## 4. Tests and Verification Plan

### 4.1. Test Suite (`tests/`)
- [`tests/test_chicken_dataset.py`](file:///home/bruno/Documents/PSAIFileHandler/tests/test_chicken_dataset.py):
  - Uses `MATConverter` to convert `data/matlab/chicken_dataset.mat` to NetCDF-4 (`chicken_dataset.nc`).
  - Verifies group counts, `T_oven` shapes, and single/all probe measurement groups.
- [`tests/test_potato_dataset.py`](file:///home/bruno/Documents/PSAIFileHandler/tests/test_potato_dataset.py):
  - Uses `MATSweepConverter` to convert `data/matlab/potato_dataset.mat` to NetCDF-4 (`potato_dataset.nc`).
  - Verifies group integrity, coordinates, and oven temperature signals.
