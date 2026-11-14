from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass(frozen=True)
class ComsolExpressionHeader:
    """Parsed representation of a COMSOL expression header."""

    expression: str
    units: str | None
    step_index: int
    parameters: dict[str, float | str] = field(default_factory=dict)
    param_units: dict[str, str] = field(default_factory=dict)
    raw_header: str = ""


# Captures expression name, optional (units), step index after '@', and trailing parameter list
HEADER_REGEX = re.compile(
    r"^(?P<expr>.*?)\s*(?:\((?P<units>[^)]+)\))?\s*@\s*(?P<step>\d+):\s*(?P<params>.*)$"
)


def parse_parameters_string(params_str: str) -> tuple[dict[str, float | str], dict[str, str]]:
    """Parse key=value [unit] parameter list from a COMSOL step segment."""
    params: dict[str, float | str] = {}
    param_units: dict[str, str] = {}

    # Splits parameter string on commas or semicolons followed by whitespace/underscores
    parts = re.split(r"[,;][_\s]*", params_str)
    for part in parts:
        cleaned = part.strip(" _\t")
        if not cleaned or "=" not in cleaned:
            continue
        # Extracts key=value and optional unit string supporting scientific notation (e.g. 5E-4 s)
        m = re.match(
            r"^(?P<key>[a-zA-Z_0-9]+)\s*=\s*(?P<val>[-+]?[0-9]*\.?[0-9]+(?:[eE][-+]?[0-9]+)?)(?:[\s_]+(?P<unit>.*))?$",
            cleaned,
        )
        if m:
            key = m.group("key").strip("_")
            raw_val = m.group("val")
            try:
                val: float | str = float(raw_val) if ("." in raw_val or "e" in raw_val.lower()) else int(raw_val)
            except ValueError:
                val = raw_val
            params[key] = val

            unit = (m.group("unit") or "").strip(" _\t")
            if unit:
                param_units[key] = unit

    return params, param_units


def parse_expression_header(header_text: str) -> ComsolExpressionHeader:
    """Parse a single COMSOL expression header string (from transposed line or VTU array name)."""
    raw = header_text.strip().lstrip("%").strip()

    normalized_vtu = raw
    if "_@_" in raw:
        normalized_vtu = raw.replace("_@_", " @ ").replace(":_", ": ")

    m = HEADER_REGEX.match(normalized_vtu)
    if not m:
        raise ValueError(f"Unable to parse COMSOL expression header: '{header_text}'")

    expr_raw = m.group("expr").strip().replace("_", " ")
    units_raw = m.group("units").strip() if m.group("units") else None
    step_idx = int(m.group("step"))
    params, param_units = parse_parameters_string(m.group("params"))

    return ComsolExpressionHeader(
        expression=expr_raw,
        units=units_raw,
        step_index=step_idx,
        parameters=params,
        param_units=param_units,
        raw_header=header_text,
    )


def parse_flat_header_line(line: str) -> tuple[list[str], list[ComsolExpressionHeader]]:
    """Parse standard (non-transposed) column header line using '@' column boundaries."""
    raw = line.strip().lstrip("%").strip()
    # Finds all '@ <step>:' column boundary markers in flat header line
    matches = list(re.finditer(r"@\s*(\d+):", raw))
    if not matches:
        raise ValueError("Header line does not contain COMSOL '@ <step>:' markers.")

    # Matches trailing expression name with optional parenthesized units at the end of a segment
    expr_pattern = re.compile(r"([a-zA-Z0-9_|.\-]+(?:\s*\([^)]*\))?)\s*$")

    prefix = raw[: matches[0].start()].strip()
    m_expr = expr_pattern.search(prefix)
    if not m_expr:
        raise ValueError(f"Could not extract leading expression from header prefix: '{prefix}'")

    first_expr_full = m_expr.group(1).strip()
    coord_part = prefix[: m_expr.start()].strip(", \t")
    # Splits leading spatial coordinate labels on whitespace or commas
    coords = [c for c in re.split(r"[\s,]+", coord_part) if c]

    headers: list[ComsolExpressionHeader] = []
    current_expr = first_expr_full

    for i in range(len(matches)):
        start = matches[i].start()
        step = int(matches[i].group(1))

        if i < len(matches) - 1:
            end = matches[i + 1].start()
            seg = raw[start:end]
            content = seg[len(matches[i].group(0)) :].strip()
            m_next = expr_pattern.search(content)
            if not m_next:
                raise ValueError(f"Failed to extract expression name between columns {i} and {i + 1}: '{content}'")
            next_expr = m_next.group(1).strip()
            params_str = content[: m_next.start()].rstrip(", \t")
        else:
            seg = raw[start:]
            content = seg[len(matches[i].group(0)) :].strip()
            params_str = content
            next_expr = None

        # Separates base expression name from trailing parenthesized units (e.g. 'u' and 'm/s')
        m_u = re.search(r"^(.*?)(?:\s*\(([^)]+)\))?$", current_expr)
        expr_name = m_u.group(1).strip() if m_u else current_expr
        units = m_u.group(2).strip() if (m_u and m_u.group(2)) else None

        params, param_units = parse_parameters_string(params_str)
        headers.append(
            ComsolExpressionHeader(
                expression=expr_name,
                units=units,
                step_index=step,
                parameters=params,
                param_units=param_units,
                raw_header=f"{current_expr} @ {step}: {params_str}",
            )
        )

        if next_expr is not None:
            current_expr = next_expr

    return coords, headers
