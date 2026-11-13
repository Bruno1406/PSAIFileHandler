"""MATLAB dataset converter and file handler package."""

from .accessors import PathAccessor, compile_accessor, evaluate_accessor
from .containers import (
    CellArray,
    MATStruct,
    MATStructArray,
    dataframe_to_dataarray,
    deserialize_matlab_value,
)
from .converter import MATConverter, build_datatree, mat_to_netcdf4
from .mat_file import MATFile
from .sweep_converter import MATSweepConverter, build_structured_sweep_mapping

__all__ = [
    "CellArray",
    "MATStruct",
    "MATStructArray",
    "MATFile",
    "MATConverter",
    "MATSweepConverter",
    "PathAccessor",
    "compile_accessor",
    "evaluate_accessor",
    "deserialize_matlab_value",
    "dataframe_to_dataarray",
    "build_datatree",
    "mat_to_netcdf4",
    "build_structured_sweep_mapping",
]
