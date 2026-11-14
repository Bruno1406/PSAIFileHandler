from __future__ import annotations

from .aliases import DEFAULT_FIELD_ALIASES, DEFAULT_REGEX_RULES, FieldAliasResolver
from .converter import ComsolConverter
from .header_parser import (
    ComsolExpressionHeader,
    parse_expression_header,
    parse_flat_header_line,
)
from .parsers import (
    BaseComsolParser,
    FlatTextParser,
    ParsedComsolGeometry,
    ParsedComsolStep,
    TransposedTextParser,
    VTUParser,
    get_parser_for_file,
    is_file_transposed,
)

__all__ = [
    "DEFAULT_FIELD_ALIASES",
    "DEFAULT_REGEX_RULES",
    "BaseComsolParser",
    "ComsolConverter",
    "ComsolExpressionHeader",
    "FieldAliasResolver",
    "FlatTextParser",
    "ParsedComsolGeometry",
    "ParsedComsolStep",
    "TransposedTextParser",
    "VTUParser",
    "get_parser_for_file",
    "is_file_transposed",
    "parse_expression_header",
    "parse_flat_header_line",
]
