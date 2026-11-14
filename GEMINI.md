# Agent Guidelines

## 1. Spec-Driven Implementation Workflow (Mandatory)
Whenever the user requests to implement something according to a specification (e.g., in `specs/` or referenced directly):
- **Do NOT proceed immediately to implementation.**
- First, rigorously review and **criticize the spec**, actively identifying weaknesses, ambiguities, or theoretical gaps.
- Ask clarifying questions across four dimensions:
  1. **Mathematics & Algorithms**: Formulations, convergence proofs/assumptions, edge cases, numerical conditioning, and coordinate invariance.
  2. **Features & Interfaces**: Method signatures, class hierarchy, data structures, and compatibility with existing components.
  3. **Testing & Validation**: Acceptance criteria, ground truth benchmarks, synthetic test cases, and tolerance thresholds.
  4. **Performance & Potential Pitfalls**: Bottlenecks, vectorized linear algebra, memory scaling, and I/O overhead.
- Wait for user alignment or answers before writing implementation code.

### Distinction: `specs/` vs. `docs/`
- **`specs/` (Specifications — Authoritative Implementation Truth)**:
  - Houses the rigorous, formal instructions required to design and implement a component or subsystem.
  - Contains exact mathematical formulations, interface contracts, class hierarchies, algorithmic complexity, numerical edge cases, and acceptance testing criteria.
  - Written for engineers and AI agents as the binding technical specification before writing code.
- **`docs/` (Documentation — User-Friendly Guides & Manuals)**:
  - Houses end-user manuals, practical developer guides, and conceptual explanations.
  - Explains *how to use* the package with concrete examples, schema references, and recommended workflows.
  - Avoids internal refactoring history, procedural migration steps, or implementation narratives (which belong exclusively in `specs/`).

---

## 2. Environment & Package Management
- **`uv` is the Mandatory Package Manager**:
  - Always use `uv` for managing dependencies, virtual environments, and running tools (e.g., `uv add <package>`, `uv run <command>`, `uv pip install`).
  - Do not invoke raw `pip` directly unless explicitly requested by the user.

---

## 3. Core Principles
- **Clean & Self-Documenting Code**: Write expressive, readable Python following the existing codebase conventions.
- **Minimal In-Function Comments**: Keep comments within function bodies strictly minimal and non-verbose.
- **Mandatory Documentation in `docs/`**: After every feature implementation or major refactoring, generate a comprehensive technical document in the `docs/` folder instead of cluttering function bodies with lengthy explanations.
- **Early Stage Development (No Retrocompatibility)**: The project is in early-stage development and nobody uses the package yet; retrocompatibility is a non-issue. Prefer clean, modern, and unencumbered architectures over legacy shims or backwards-compatibility layers.

---

## 4. Python Coding Style
- **Type Annotations**:
  - Use modern typing conventions: `list[...]`, `dict[...]`, `tuple[...]`, `X | None`, and explicit collections from `typing` (`Sequence`, `Mapping`, `Iterable`, `Protocol`).
  - Use `np.ndarray` and PyVista types (`pv.UnstructuredGrid`, `pv.PolyData`) for mesh and field data.
- **No Functions Defined in `__init__.py` Files**:
  - `__init__.py` files must strictly serve as package namespace roots, exposing public APIs via `__all__` and re-exports.
  - Never define functions, classes, or computational methods directly in `__init__.py` files. All implementations must reside in dedicated module files (e.g. `base.py`, `converter.py`, `accessors.py`).

---

## 5. In-Function Comments Policy
- **No Verbose Comments**: Do not write paragraph-long explanations, step-by-step prose, or tutorials inside function bodies.
- **Minimal Annotations Only**: Only use brief, single-line comments for non-obvious operations (e.g. index mapping, vector transformations, unit conversions).
- **Docstrings**:
  - Provide clear, concise docstrings for all public classes and functions.
  - State the purpose, parameter descriptions with physical units (e.g. RPM, m³/h, rad/s, K, s), and return values.
- **Inline `#Comment` Review Workflow**:
  - Whenever the user writes a comment starting with `#Comment` (or `# Comment`) and instructs the agent to revise/review a file or a group of files:
  - The agent must address each question thoroughly in its response and/or code adjustments.
  - The agent must delete the `#Comment` comments from the file(s) afterwards to keep the codebase clean.

---

## 6. Unified NetCDF-4 / HDF5 Data Format Specification

The repository standardizes heterogeneous physical simulation data (COMSOL, OpenFOAM, ANSYS, experimental test benches) into a unified, CF-compliant NetCDF-4 hierarchical format (`xarray.DataTree` / `h5netcdf` / `netcdf4`).

### 6.1. General Hierarchy: `Experiment -> Geometry -> Data`
The hierarchical tree follows a clean three-tier structure:
```text
/ (Root)
│  Attributes: title, institution, contact, conventions="CF-1.8", source, total_experiments
│
├── /{experiment_name}/                   # Experiment / run group (e.g. "run_01", "sweep_rpm3000")
│   │  Attributes: run_metadata, operating_conditions, embedded config/schedules
│   │
│   ├── Experiment-Level Variables (NO spatial node dimension):
│   │   ├── time              (time: T)           # [OPTIONAL] Physical simulation time [s]
│   │   ├── Operating_RPM     () or (time)        # Scalar parameter or driving input
│   │   ├── Mass_Flow_Rate    () or (time)        # Exogenous boundary condition or global metric
│   │   └── Volume_Avg_Temp   () or (time)        # Domain-integrated / averaged scalar
│   │
│   ├── /{geometry_name_1}/               # First spatial domain / component (e.g. "volute", "matrix")
│   │   │  Dimensions & Coordinates:
│   │   │   ├── node          (node: N_1)         # Mesh node scale for geometry 1
│   │   │   ├── spatial       (spatial: 3)        # Dimension names: ['x', 'y', 'z']
│   │   │   └── coordinates   (node, spatial)     # Absolute node coordinates [m]
│   │   │
│   │   └── Spatially Distributed Fields:
│   │       ├── Pressure      (node) or (time, node)  # Static or transient spatial field
│   │       └── Velocity_Mag  (node) or (time, node)  # Static or transient spatial field
│   │
│   ├── /{geometry_name_2}/               # Additional spatial subdomains (e.g. "impeller", "outlet")
│   │   │  Dimensions & Coordinates: node (N_2), spatial (3), coordinates (N_2, 3)
│   │   └── Spatially Distributed Fields: Pressure, Velocity, ...
│   │
│   └── /probes/ or /{probe_name}/        # Probes / sensors (1-point geometry edge case)
│       │  Attributes: probe_coordinates = [x, y, z] (or array coordinates)
│       └── Variables: Temperature (time), Pressure (time), ...
```

---

### 6.2. Experiment Level (Non-Spatial Data)
- **Scope**: Resides directly at `/{experiment_name}/`.
- **Exclusion Rule**: Contains **only** data arrays that do **NOT** have a `node` coordinate.
- **Content**:
  - Global scalar parameters, operational inputs, and boundary forcing schedules (e.g., flow rates, heat fluxes, RPM schedules, ambient conditions).
  - Spatially aggregated or integrated quantities (e.g., volume-averaged temperature, total mass, surface-integrated reaction rates).
  - The physical meaning of the variable is flexible; the sole structural requirement is the complete absence of spatial mesh `node` dimensions.
- **Embedded Provenance**: Raw configuration files, tabular boundary condition schedules, or solver logs must be stored directly as string attributes on the experiment group.

---

### 6.3. Geometry Level (Spatial Fields & Domain Decomposition)
- **Scope**: Child groups residing at `/{experiment_name}/{geometry_name}/`.
- **Domain Decomposition**: An experiment may contain one or multiple geometry groups (e.g., partitioning a centrifugal pump into `volute`, `blades`, `inlet`, `outlet`; or separating fluid and solid continuum domains).
- **Independent Discretization**: Each geometry group defines its own spatial mesh coordinate scales:
  1. `node` (node: $N_g$): 1D integer index scale `[0, ..., N_g-1]` for the nodes belonging to this geometry.
  2. `spatial` (spatial: 3 or 2): Coordinate dimension scale (`['x', 'y', 'z']` or `['x', 'y']`).
  3. `coordinates` (node, spatial): 2D float array specifying absolute Cartesian coordinates in meters (`m`).
- **Distributed Fields**: All spatial variables defined on this geometry are stored within this group:
  - **Static simulations**: Indexed as `(node)` or `(node, ...)`.
  - **Transient simulations**: Indexed as `(time, node)` or `(time, node, ...)`, with `time` as the leading dimension.

---

### 6.4. Time as an Optional Coordinate
- **Time is not mandatory**: The unified format natively accommodates both static (steady-state) and transient (dynamic) simulations.
- **Static / Steady-State**:
  - No `time` dimension or coordinate is defined.
  - Experiment-level variables are 0D scalars or indexed by parametric sweep coordinates.
  - Geometry-level fields are indexed strictly by `(node)` or `(node, spatial)`.
- **Transient / Dynamic**:
  - A 1D monotonically increasing float coordinate `time` (time: $T$) in seconds (`s`) is present.
  - Experiment-level signals are indexed by `(time)`.
  - Geometry-level fields are indexed by `(time, node)`.

---

### 6.5. Probe & Sensor Handling (1-Point Geometry Edge Case)
Probes and localized physical point sensors are treated as a 1-point spatial geometry edge case:
- **User-Defined Grouping Policy**: When multiple probes exist, the ingestion pipeline and user determine whether:
  1. **Individual Probe Groups**: Each probe has its own dedicated group (e.g., `/{experiment_name}/{probe_name}/`), containing a fixed attribute `probe_coordinates = [x, y, z]` and 1D temporal signals `(time)` without a node dimension.
  2. **Aggregated Probes Group**: Probes are combined into a single group (e.g., `/{experiment_name}/probes/`), defining a discrete `probe_id` dimension (or `node: P`) with a corresponding coordinates array `coordinates: (probe_id, spatial)`.

---

### 6.6. Metadata, Validation & Compression
- **Attributes**: Every variable must define `units` (e.g., `K`, `s`, `m`, `kg/m^3`, `Pa`, `1`), `long_name`, and optional `standard_name`.
- **Zero-NaN Integrity**: Ingested datasets must undergo strict validation ensuring zero unphysical `NaN` or `Inf` values within valid domains.
- **Compression**: Use HDF5 chunking along the leading dimension (`time` for transient fields, `node` for large static meshes) and deflate compression (`complevel=4`, `shuffle=True`).
- **Engine Compatibility**: All files must open seamlessly across `h5netcdf`, `netcdf4`, and `xarray.DataTree`.

---

## 7. Documentation Standards for `docs/`
After completing any feature implementation or architectural change, you **MUST** create or update a user-friendly markdown guide in `docs/` (e.g., `docs/<FEATURE_NAME>.md`). 

The document should be focused on enabling developers and researchers to use the subsystem effortlessly:

### Guide Template
1. **Title & Conceptual Overview**:
   - `# <Feature / Subsystem Name> User Guide`
   - High-level overview of purpose, supported physical domains, and key capabilities.
2. **Quickstart & Common Workflows**:
   - Minimal working examples showing how to ingest data and export to NetCDF-4.
3. **Data Schemas & Configuration**:
   - Comprehensive explanation of dictionary formats, schema parameters, and accessors.
   - Hierarchy visualization mapping input fields to the NetCDF-4 tree structure.
4. **Advanced Features & Edge Cases**:
   - Dynamic evaluation, multi-domain decomposition, coordinate invariance, and probe extraction.
5. **API & Reference Guide**:
   - Concise reference for public classes, methods, and parameters.
