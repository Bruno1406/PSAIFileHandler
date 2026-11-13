from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np

from .containers import MATStructArray, deserialize_matlab_value

try:
    import matlab.engine as matlab_engine
except ImportError:
    matlab_engine = None  # type: ignore[assignment]


class MATFile:
    """MAT file reader leveraging matlabengine native deserialization into Python structures."""

    file_path: Path
    license_path: Path | None
    _eng: Any | None

    def __init__(self, file_path: str | Path, license_path: str | Path | None = None) -> None:
        self.file_path = Path(file_path).resolve()
        self.license_path = Path(license_path).resolve() if license_path is not None else None
        self._eng = None

        if not self.file_path.exists():
            raise FileNotFoundError(f"File not found: {self.file_path}")
        if self.license_path is not None and not self.license_path.exists():
            raise FileNotFoundError(f"License file not found: {self.license_path}")

    def _get_engine(self) -> Any:
        """Start or return the active MATLAB engine."""
        if self._eng is None:
            if matlab_engine is None:
                raise ImportError(
                    "matlab.engine is required to read MATLAB files. "
                    "Ensure MATLAB and its Python engine are installed."
                )
            cmd = f"-c {self.license_path}" if self.license_path else ""
            self._eng = matlab_engine.start_matlab(cmd) if cmd else matlab_engine.start_matlab()
        return self._eng

    def read(self, preload: bool = False, max_elements: int | None = None) -> dict[str, Any]:
        """Read .mat file via matlabengine and return parsed workspace dictionary."""
        eng = self._get_engine()
        eng.eval("clearvars;", nargout=0)
        escaped_path = str(self.file_path).replace("'", "''")
        eng.eval(f"load('{escaped_path}')", nargout=0)

        var_names = eng.eval("who", nargout=1)
        result: dict[str, Any] = {}

        for var in var_names:
            var_cls = eng.eval(f"class({var})", nargout=1)
            var_sz = eng.eval(f"size({var})", nargout=1)
            shape = tuple(int(s) for s in var_sz[0])
            num_elements = int(np.prod(shape))

            if var_cls == "struct":
                fields = eng.eval(f"fieldnames({var})", nargout=1)
                if num_elements > 1:
                    struct_arr = MATStructArray(eng, var, shape, fields)
                    if preload:
                        struct_arr.preload(max_elements=max_elements)
                    result[var] = struct_arr
                else:
                    raw_struct = eng.eval(f"{var}(1)", nargout=1)
                    result[var] = deserialize_matlab_value(raw_struct)
            elif var_cls == "table":
                result[var] = deserialize_matlab_value(eng.workspace[var])
            else:
                raw_val = eng.eval(var, nargout=1)
                result[var] = deserialize_matlab_value(raw_val)

        return result

    def close(self) -> None:
        """Close the underlying MATLAB engine process if running."""
        if self._eng is not None:
            try:
                self._eng.quit()
            finally:
                self._eng = None

    def __enter__(self) -> MATFile:
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.close()

    def __repr__(self) -> str:
        return f"<MATFile path='{self.file_path.name}'>"
