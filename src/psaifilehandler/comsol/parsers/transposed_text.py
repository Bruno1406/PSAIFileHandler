from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping

import numpy as np

from ..header_parser import ComsolExpressionHeader, parse_expression_header
from .base import BaseComsolParser, ParsedComsolGeometry, ParsedComsolStep


class TransposedTextParser(BaseComsolParser):
    """Parser for transposed COMSOL text and CSV exports."""

    def parse(
        self,
        geometry_name: str,
        coord_names: list[str],
        variable_schema: Mapping[str, str | list[str]],
        time_param: str | None = None,
    ) -> ParsedComsolGeometry:
        sep = "," if self.file_path.suffix.lower() == ".csv" else " "

        coord_clean_names = [c.strip().lower() for c in coord_names]
        coord_arrays: dict[str, np.ndarray] = {}

        scalar_targets: dict[str, str] = {}
        vector_targets: dict[str, list[str]] = {}
        for target_name, spec in variable_schema.items():
            if isinstance(spec, list):
                vector_targets[target_name] = [str(x) for x in spec]
            else:
                scalar_targets[target_name] = str(spec)

        step_scalars: dict[int, dict[str, np.ndarray]] = defaultdict(dict)
        step_vectors: dict[int, dict[str, dict[int, np.ndarray]]] = defaultdict(lambda: defaultdict(dict))
        step_metadata: dict[int, ComsolExpressionHeader] = {}
        field_units: dict[str, str] = {}
        param_units: dict[str, str] = {}

        with open(self.file_path, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                if not line.startswith("%"):
                    continue

                clean_header = line.strip().lstrip("%").strip()
                lower_header = clean_header.lower()

                if lower_header in coord_clean_names and "@" not in clean_header:
                    val_line = next(f, None)
                    if val_line is not None:
                        coord_arrays[lower_header] = np.fromstring(val_line, sep=sep, dtype=np.float64)
                    continue

                if "@" in clean_header:
                    header = parse_expression_header(clean_header)
                    step_idx = header.step_index
                    if step_idx not in step_metadata:
                        step_metadata[step_idx] = header
                    param_units.update(header.param_units)

                    matched_target: str | None = None
                    matched_comp: int | None = None

                    for t_name, pat in scalar_targets.items():
                        if self.alias_resolver.matches(pat, header.expression):
                            matched_target = t_name
                            matched_comp = None
                            break

                    if matched_target is None:
                        for t_name, comps in vector_targets.items():
                            for c_idx, c_pat in enumerate(comps):
                                if self.alias_resolver.matches(c_pat, header.expression):
                                    matched_target = t_name
                                    matched_comp = c_idx
                                    break
                            if matched_target is not None:
                                break

                    if matched_target is not None:
                        val_line = next(f, None)
                        if val_line is None:
                            break
                        arr = np.fromstring(val_line, sep=sep, dtype=np.float64)
                        if header.units and matched_target not in field_units:
                            field_units[matched_target] = header.units

                        if matched_comp is None:
                            step_scalars[step_idx][matched_target] = arr
                        else:
                            step_vectors[step_idx][matched_target][matched_comp] = arr
                    else:
                        _ = next(f, None)

        missing_coords = [c for c in coord_clean_names if c not in coord_arrays]
        if missing_coords:
            raise ValueError(f"Missing coordinates {missing_coords} in {self.file_path.name}")

        stacked_coords = np.column_stack([coord_arrays[c] for c in coord_clean_names])

        sorted_steps: list[ParsedComsolStep] = []
        for step_idx in sorted(step_metadata.keys()):
            meta = step_metadata[step_idx]
            step_fields: dict[str, np.ndarray] = dict(step_scalars.get(step_idx, {}))

            if step_idx in step_vectors:
                for v_name, comps_dict in step_vectors[step_idx].items():
                    n_expected = len(vector_targets[v_name])
                    if len(comps_dict) != n_expected:
                        raise ValueError(
                            f"Step {step_idx} missing vector components for '{v_name}': "
                            f"expected {n_expected}, got {len(comps_dict)}"
                        )
                    comp_list = [comps_dict[i] for i in range(n_expected)]
                    step_fields[v_name] = np.column_stack(comp_list)

            time_val: float | None = None
            exp_params = dict(meta.parameters)
            if time_param is not None:
                for p_key, p_val in list(exp_params.items()):
                    if p_key.lower() == time_param.lower():
                        time_val = float(p_val)
                        del exp_params[p_key]
                        break

            sorted_steps.append(
                ParsedComsolStep(
                    step_index=step_idx,
                    parameters=meta.parameters,
                    param_units=meta.param_units,
                    time_value=time_val,
                    experiment_params=exp_params,
                    fields=step_fields,
                )
            )

        return ParsedComsolGeometry(
            geometry_name=geometry_name,
            coordinates=stacked_coords,
            spatial_coords=coord_names,
            steps=sorted_steps,
            field_units=field_units,
            param_units=param_units,
        )

    def inspect(self) -> tuple[list[str], list[str], dict[str, float | str], dict[str, str]]:
        """Inspect file header and return (coordinates, expressions, sample_parameters, param_units)."""
        coords: list[str] = []
        expressions: list[str] = []
        seen: set[str] = set()
        step_params: dict[str, float | str] = {}
        param_units: dict[str, str] = {}

        with open(self.file_path, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                if not line.startswith("%"):
                    continue
                clean = line.strip().lstrip("%").strip()
                lower = clean.lower()
                if lower in ("x", "y", "z") and "@" not in clean:
                    if lower not in coords:
                        coords.append(lower)
                    continue
                if "@" in clean:
                    h = parse_expression_header(clean)
                    if seen and h.step_index > 1:
                        break
                    if h.expression not in seen:
                        seen.add(h.expression)
                        expressions.append(h.expression)
                    step_params.update(h.parameters)
                    param_units.update(h.param_units)

        return coords, expressions, step_params, param_units
