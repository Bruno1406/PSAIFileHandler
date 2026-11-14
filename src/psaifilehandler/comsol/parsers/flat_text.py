from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping

import numpy as np

from ..header_parser import ComsolExpressionHeader, parse_flat_header_line
from .base import BaseComsolParser, ParsedComsolGeometry, ParsedComsolStep


class FlatTextParser(BaseComsolParser):
    """Parser for standard (non-transposed) COMSOL text and CSV exports."""

    def parse(
        self,
        geometry_name: str,
        coord_names: list[str],
        variable_schema: Mapping[str, str | list[str]],
        time_param: str | None = None,
    ) -> ParsedComsolGeometry:
        delimiter = "," if self.file_path.suffix.lower() == ".csv" else None

        header_line = ""
        with open(self.file_path, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                if line.startswith("%") and "@" in line:
                    header_line = line
                    break

        if not header_line:
            raise ValueError(f"No column header line found with '@' markers in {self.file_path.name}")

        file_coords, expr_headers = parse_flat_header_line(header_line)

        file_coord_clean = [c.strip().lower() for c in file_coords]
        target_coord_clean = [c.strip().lower() for c in coord_names]

        coord_col_map: dict[str, int] = {}
        for c_target in target_coord_clean:
            if c_target in file_coord_clean:
                coord_col_map[c_target] = file_coord_clean.index(c_target)
            else:
                raise ValueError(
                    f"Requested coordinate '{c_target}' not found in file coordinates {file_coords}"
                )

        scalar_targets: dict[str, str] = {}
        vector_targets: dict[str, list[str]] = {}
        for target_name, spec in variable_schema.items():
            if isinstance(spec, list):
                vector_targets[target_name] = [str(x) for x in spec]
            else:
                scalar_targets[target_name] = str(spec)

        offset = len(file_coords)
        step_scalars: dict[int, dict[str, int]] = defaultdict(dict)
        step_vectors: dict[int, dict[str, dict[int, int]]] = defaultdict(lambda: defaultdict(dict))
        step_metadata: dict[int, ComsolExpressionHeader] = {}
        field_units: dict[str, str] = {}
        param_units: dict[str, str] = {}

        for j, h in enumerate(expr_headers):
            abs_col = offset + j
            step_idx = h.step_index
            if step_idx not in step_metadata:
                step_metadata[step_idx] = h
            param_units.update(h.param_units)

            matched_target: str | None = None
            matched_comp: int | None = None

            for t_name, pat in scalar_targets.items():
                if self.alias_resolver.matches(pat, h.expression):
                    matched_target = t_name
                    matched_comp = None
                    break

            if matched_target is None:
                for t_name, comps in vector_targets.items():
                    for c_idx, c_pat in enumerate(comps):
                        if self.alias_resolver.matches(c_pat, h.expression):
                            matched_target = t_name
                            matched_comp = c_idx
                            break
                    if matched_target is not None:
                        break

            if matched_target is not None:
                if h.units and matched_target not in field_units:
                    field_units[matched_target] = h.units

                if matched_comp is None:
                    step_scalars[step_idx][matched_target] = abs_col
                else:
                    step_vectors[step_idx][matched_target][matched_comp] = abs_col

        usecols_set: set[int] = set()
        for c_idx in coord_col_map.values():
            usecols_set.add(c_idx)

        for s_dict in step_scalars.values():
            for col in s_dict.values():
                usecols_set.add(col)

        for v_dict in step_vectors.values():
            for c_dict in v_dict.values():
                for col in c_dict.values():
                    usecols_set.add(col)

        sorted_usecols = sorted(usecols_set)
        col_to_matrix_idx = {col: i for i, col in enumerate(sorted_usecols)}

        data_matrix = np.loadtxt(
            self.file_path,
            comments="%",
            delimiter=delimiter,
            usecols=sorted_usecols,
            dtype=np.float64,
        )

        if data_matrix.ndim == 1:
            data_matrix = data_matrix[np.newaxis, :]

        stacked_coords = np.column_stack([
            data_matrix[:, col_to_matrix_idx[coord_col_map[c]]]
            for c in target_coord_clean
        ])

        sorted_steps: list[ParsedComsolStep] = []
        for step_idx in sorted(step_metadata.keys()):
            meta = step_metadata[step_idx]
            step_fields: dict[str, np.ndarray] = {}

            if step_idx in step_scalars:
                for var_name, abs_col in step_scalars[step_idx].items():
                    step_fields[var_name] = data_matrix[:, col_to_matrix_idx[abs_col]]

            if step_idx in step_vectors:
                for var_name, comp_dict in step_vectors[step_idx].items():
                    n_expected = len(vector_targets[var_name])
                    if len(comp_dict) != n_expected:
                        raise ValueError(
                            f"Step {step_idx} missing vector components for '{var_name}': "
                            f"expected {n_expected}, got {len(comp_dict)}"
                        )
                    comp_cols = [
                        data_matrix[:, col_to_matrix_idx[comp_dict[i]]]
                        for i in range(n_expected)
                    ]
                    step_fields[var_name] = np.column_stack(comp_cols)

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
