from __future__ import annotations

from .base import (
    BaseComsolParser,
    ParsedComsolGeometry,
    ParsedComsolStep,
    get_parser_for_file,
    is_file_transposed,
)
from .flat_text import FlatTextParser
from .transposed_text import TransposedTextParser
from .vtu_parser import VTUParser

__all__ = [
    "BaseComsolParser",
    "FlatTextParser",
    "ParsedComsolGeometry",
    "ParsedComsolStep",
    "TransposedTextParser",
    "VTUParser",
    "get_parser_for_file",
    "is_file_transposed",
]

