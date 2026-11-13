# PSAIFileHandler

Standardized simulation and experimental data file handler for OpenFOAM, COMSOL, and MATLAB converting heterogeneous engineering datasets into CF-compliant NetCDF-4/HDF5 format.

## Overview

`PSAIFileHandler` standardizes heterogeneous physical simulation data (COMSOL, OpenFOAM, ANSYS, MATLAB/experimental test benches) into a unified, CF-compliant NetCDF-4 hierarchical format (`xarray.DataTree` / `h5netcdf` / `netcdf4`) conforming to the specifications outlined in [GEMINI.md](file:///home/bruno/Documents/PSAIMiddleware/GEMINI.md).

## Repository Structure

```text
.
├── data/              # Raw simulation and experimental datasets
│   ├── comsol/        # COMSOL VTU/TXT export datasets
│   └── matlab/        # MATLAB MAT-file datasets
├── docs/              # Architectural and technical documentation
├── specs/             # Feature, algorithmic, and mathematical specifications
├── src/               # Source packages
│   ├── comsol/        # COMSOL ingestion, geometry splitting, and field mapping
│   ├── matlab/        # MATLAB struct/cell-array handling and MAT-file converters
│   └── openfoam/      # OpenFOAM case and result handlers
├── GEMINI.md          # Project guidelines and NetCDF-4 schema specification
├── pyproject.toml     # Project metadata and dependencies
└── README.md
```

## Dependencies & Environment

Manage dependencies using `uv`:

```bash
uv sync
```
