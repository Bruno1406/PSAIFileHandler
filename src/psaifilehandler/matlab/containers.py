from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

import numpy as np
import pandas as pd
import xarray as xr


class CellArray(np.ndarray):
    """NumPy object array preserving MATLAB cell array container geometry."""

    def __new__(cls, input_array: Sequence[Any] | np.ndarray) -> CellArray:
        return np.asanyarray(input_array, dtype=object).view(cls)

    def __getitem__(self, item: Any) -> Any:
        if isinstance(item, (int, np.integer)) and self.ndim == 2 and 1 in self.shape:
            return self.flat[item]
        return super().__getitem__(item)


class MATStruct(Mapping[str, Any]):
    """Python representation of a MATLAB struct supporting attribute and key access."""

    def __init__(self, fields: dict[str, Any]) -> None:
        self.__dict__["_fields"] = fields

    def __getattr__(self, name: str) -> Any:
        if name in self._fields:
            return self._fields[name]
        raise AttributeError(f"Struct has no field '{name}'. Available: {list(self._fields.keys())}")

    def __setattr__(self, name: str, value: Any) -> None:
        if name == "_fields":
            super().__setattr__(name, value)
        else:
            self._fields[name] = value

    def __getitem__(self, key: str) -> Any:
        if key in self._fields:
            return self._fields[key]
        raise KeyError(f"Field '{key}' not found in struct. Available: {list(self._fields.keys())}")

    def __contains__(self, key: object) -> bool:
        return key in self._fields

    def __iter__(self):
        return iter(self._fields)

    def __len__(self) -> int:
        return len(self._fields)

    def to_dict(self) -> dict[str, Any]:
        """Return a copy of the underlying fields dictionary."""
        return dict(self._fields)

    def __repr__(self) -> str:
        return f"MATStruct({list(self._fields.keys())})"


class MATStructArray(Sequence[MATStruct]):
    """Subscriptable sequence of structs with on-demand engine deserialization and caching."""

    def __init__(self, eng: Any, var_name: str, shape: tuple[int, ...], fields: list[str]) -> None:
        self._eng = eng
        self._var_name = var_name
        self._shape = shape
        self._fields = fields
        self._size = max(shape) if len(shape) == 2 and 1 in shape else int(np.prod(shape))
        self._cache: dict[int, MATStruct] = {}

    def __len__(self) -> int:
        return self._size

    @property
    def shape(self) -> tuple[int, ...]:
        return self._shape

    @property
    def fieldnames(self) -> list[str]:
        return list(self._fields)

    def _linear_to_matlab(self, idx: int) -> int:
        if idx < 0:
            idx += self._size
        if idx < 0 or idx >= self._size:
            raise IndexError(f"Index {idx} out of range for struct array of size {self._size}")
        return idx + 1

    def __getitem__(self, index: Any) -> Any:
        if isinstance(index, slice):
            return [self[i] for i in range(*index.indices(self._size))]

        if isinstance(index, tuple):
            if len(index) == 2 and len(self._shape) == 2:
                r, c = index
                r = r + self._shape[0] if r < 0 else r
                c = c + self._shape[1] if c < 0 else c
                return self[c * self._shape[0] + r]
            raise IndexError(f"Invalid index {index} for struct array of shape {self._shape}")

        if not isinstance(index, (int, np.integer)):
            raise TypeError(f"Index must be integer, tuple, or slice, not {type(index).__name__}")

        matlab_idx = self._linear_to_matlab(int(index))
        cache_key = matlab_idx - 1

        if cache_key in self._cache:
            return self._cache[cache_key]

        if self._eng is None:
            raise RuntimeError("MATLAB engine is closed; cannot fetch uncached struct array elements.")

        raw_struct = self._eng.eval(f"{self._var_name}({matlab_idx})", nargout=1)
        parsed = deserialize_matlab_value(raw_struct)
        self._cache[cache_key] = parsed
        return parsed

    def preload(self, max_elements: int | None = None) -> list[MATStruct]:
        """Preload elements into cache and return them as a list."""
        limit = self._size if max_elements is None else min(self._size, max_elements)
        return [self[i] for i in range(limit)]

    def __repr__(self) -> str:
        return f"<MATStructArray '{self._var_name}' shape={self._shape} len={self._size} fields={self._fields}>"


def dataframe_to_dataarray(df: pd.DataFrame) -> xr.DataArray:
    """Convert a pandas DataFrame deserialized from a MATLAB table into an xarray DataArray."""
    data = np.array(df.to_numpy(), copy=True)
    row_coords = np.array(df.index.values, copy=True)
    col_coords = np.array(df.columns.values, copy=True)

    return xr.DataArray(
        data,
        dims=["row", "col"],
        coords={
            "row": row_coords,
            "col": col_coords,
            "column": ("col", col_coords),
        },
    )


def deserialize_matlab_value(val: Any) -> Any:
    """Recursively deserialize a MATLAB engine return value into Python structures."""
    if val is None:
        return None

    if isinstance(val, pd.DataFrame):
        return dataframe_to_dataarray(val)

    if isinstance(val, dict):
        return MATStruct({k: deserialize_matlab_value(v) for k, v in val.items()})

    if isinstance(val, list):
        converted = [deserialize_matlab_value(item) for item in val]
        if converted and all(isinstance(item, xr.DataArray) for item in converted):
            arr = np.empty((1, len(converted)), dtype=object)
            for j, item in enumerate(converted):
                arr[0, j] = item
            return CellArray(arr)
        return converted

    val_type = type(val)
    if "matlab." in val_type.__module__ or val_type.__name__ in (
        "double", "single", "logical", "int8", "int16", "int32", "int64",
        "uint8", "uint16", "uint32", "uint64"
    ):
        arr = np.array(val, copy=True)
        if arr.size == 1 and arr.ndim <= 2 and (arr.shape in ((1, 1), (1,), ())):
            item = arr.item()
            if isinstance(item, (np.floating, float)):
                return float(item)
            if isinstance(item, (np.integer, int)):
                return int(item)
            if isinstance(item, (np.bool_, bool)):
                return bool(item)
            return item
        return arr

    if isinstance(val, (np.floating, float)):
        return float(val)
    if isinstance(val, (np.integer, int)):
        return int(val)
    if isinstance(val, (np.bool_, bool)):
        return bool(val)
    if isinstance(val, str):
        return str(val)

    return val
