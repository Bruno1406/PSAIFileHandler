from __future__ import annotations

import re
from abc import ABC, abstractmethod
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from ..aliases import FieldAliasResolver


@dataclass
class ParsedComsolStep:
    """Extracted data and parameters for a single COMSOL step."""

    step_index: int
    parameters: dict[str, float | str]
    param_units: dict[str, str]
    time_value: float | None
    experiment_params: dict[str, float | str]
    fields: dict[str, np.ndarray]  # var_name -> array of shape (N,) or (N, d)


@dataclass
class ParsedComsolGeometry:
    """Complete parsed geometry representation across all sweep steps."""

    geometry_name: str
    coordinates: np.ndarray  # shape (N, d)
    spatial_coords: list[str]  # ['x', 'y'] or ['x', 'y', 'z']
    steps: list[ParsedComsolStep]
    field_units: dict[str, str] = field(default_factory=dict)
    param_units: dict[str, str] = field(default_factory=dict)


class BaseComsolParser(ABC):
    """Abstract interface for COMSOL file parsers."""

    def __init__(
        self,
        file_path: str | Path,
        alias_resolver: FieldAliasResolver | None = None,
    ) -> None:
        self.file_path = Path(file_path).resolve()
        self.alias_resolver = alias_resolver or FieldAliasResolver()

    @abstractmethod
    def parse(
        self,
        geometry_name: str,
        coord_names: list[str],
        variable_schema: Mapping[str, str | list[str]],
        time_param: str | None = None,
    ) -> ParsedComsolGeometry:
        """Parse the geometry file and extract coordinates and matched variables."""
        ...

    @abstractmethod
    def inspect(self) -> tuple[list[str], list[str], dict[str, float | str], dict[str, str]]:
        """Inspect file header and return (coordinates, expressions, sample_parameters, param_units)."""
        ...


def is_file_transposed(file_path: str | Path) -> bool:
    """Detect if a text or CSV export is in transposed format by inspecting header lines."""
    p = Path(file_path).resolve()
    with open(p, "r", encoding="utf-8", errors="replace") as f:
        for _ in range(25):
            line = f.readline()
            if not line:
                break
            line = line.strip()
            # Matches isolated single coordinate line '% x' or '% y' (identifies transposed format)
            if re.match(r"^%\s*[xyz]\s*$", line, re.IGNORECASE):
                return True
            # Matches multi-coordinate header '% x, y' (identifies standard flat format)
            if re.match(r"^%\s*[xyz][,\s]+[xyz]", line, re.IGNORECASE):
                return False
    return False


def get_parser_for_file(
    file_path: str | Path,
    transposed: bool | None = None,
    alias_resolver: FieldAliasResolver | None = None,
) -> BaseComsolParser:
    """Select and instantiate the appropriate COMSOL parser for a file."""
    from .flat_text import FlatTextParser
    from .transposed_text import TransposedTextParser
    from .vtu_parser import VTUParser

    p = Path(file_path).resolve()
    ext = p.suffix.lower()

    if ext == ".vtu":
        return VTUParser(p, alias_resolver=alias_resolver)

    if ext in (".txt", ".csv", ".tsv"):
        is_trans = is_file_transposed(p) if transposed is None else transposed
        if is_trans:
            return TransposedTextParser(p, alias_resolver=alias_resolver)
        return FlatTextParser(p, alias_resolver=alias_resolver)

    raise ValueError(f"Unsupported COMSOL export extension: '{ext}' for file {p.name}")

