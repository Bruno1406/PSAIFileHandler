import csv
import numpy as np
import pyvista as pv
import xarray as xr
from pathlib import Path


class ComsolFileHandler:
    
    CANONICAL_FIELD_ALIASES = {
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
        "u": "vx",
        "ux": "vx",
        "vy": "vy",
        "velocity_y": "vy",
        "v_y": "vy",
        "v": "vy",
        "uy": "vy",
        "vz": "vz",
        "velocity_z": "vz",
        "v_z": "vz",
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

    

    file_path: Path
    transpose: bool
    extension: str
    data: xr.DataTree
    parameters: list[str] | None
    fields: list[str] | None
    canonical: bool

    def __init__(self, file_path: Path, transpose: bool = True, canonical: bool = True, 
                 parameters: list[str] | None = None, fields: list[str] | None = None):
        self.file_path = file_path
        self.transpose = transpose
        self.canonical = canonical
        self.extension =''.join(Path(file_path).suffixes)
        self.data = self._read_file()
        self.parameters = parameters
        self.fields = fields



    def _read_file(self) -> xr.DataTree:
        if self.extension == ".csv" or self.extension == ".txt":
            if self.transpose:
                return self._read_flat_file_transposed()
            else:
                return self._read_flat_file()
        elif self.extension == ".vtm.series":
            return self._read_vtm_series()
        elif self.extension == ".vtu":
            return self._read_vtu()
        else:
            raise ValueError(f"Unsupported file extension: {self.extension}")

    def _read_flat_file_transposed(self) -> xr.DataTree:
        header = []
        
        with open(self.file_path, "r") as f:
            for index, line in enumerate(f):
                if index == 0:
                    header = line.strip().split(",")
                    break
        pass    

    def _read_flat_file(self) -> xr.DataTree:
        pass

    def _read_vtm_series(self) -> xr.DataTree:
        pass

    def _read_vtu(self) -> xr.DataTree:
        pass