from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

import numpy as np
import xarray as xr

from .aliases import FieldAliasResolver
from .parsers import ParsedComsolGeometry, get_parser_for_file


def _sanitize_comsol_attrs(attrs: Mapping[str, Any]) -> dict[str, Any]:
    """Sanitize attributes for CF-compliant NetCDF-4 export."""
    clean = {}
    for k, v in attrs.items():
        if v is None:
            continue
        if isinstance(v, (bool, np.bool_)):
            clean[str(k)] = int(v)
        elif isinstance(v, (str, int, float, np.integer, np.floating)):
            clean[str(k)] = v
        elif isinstance(v, (list, tuple)):
            if all(isinstance(x, (int, float, np.integer, np.floating)) for x in v):
                clean[str(k)] = list(v)
            else:
                clean[str(k)] = [str(x) for x in v]
        else:
            clean[str(k)] = str(v)
    return clean


class ComsolConverter:
    """Orchestrates parsing of COMSOL exports and standardization into hierarchical NetCDF-4."""

    def __init__(
        self,
        data_schema: dict[str, Any],
        exp_naming: str | Callable[[dict[str, Any], int], str] | None = "run_{step:03d}",
        custom_aliases: Mapping[str, str] | None = None,
    ) -> None:
        self.data_schema = data_schema
        self.exp_naming = exp_naming
        self.alias_resolver = FieldAliasResolver(custom_aliases=custom_aliases)

        self.top_vars: dict[str, str] = dict(self.data_schema.get("variables", {}))
        self.time_param: str | None = self.data_schema.get("time")

        reserved = {"variables", "time", "attrs", "metadata", "root_attrs", "root_metadata"}
        self.geometry_schemas: dict[str, dict[str, Any]] = {
            k: v for k, v in self.data_schema.items() if k not in reserved and isinstance(v, dict)
        }

    def _format_exp_name(self, params: dict[str, Any], step_idx: int, run_idx: int) -> str:
        """Resolve clean experiment name from parameters and step index."""
        if callable(self.exp_naming):
            return self.exp_naming(params, step_idx)
        if isinstance(self.exp_naming, str):
            ctx = {"step": step_idx, "index": run_idx, **params}
            return self.exp_naming.format(**ctx)
        return f"run_{step_idx:03d}"

    def to_datatree(
        self,
        files: dict[str, str | Path] | str | Path,
        transposed: dict[str, bool] | bool | None = None,
    ) -> xr.DataTree:
        """Parse geometry files and construct an xarray.DataTree."""
        file_map: dict[str, Path] = {}
        if isinstance(files, (str, Path)):
            if len(self.geometry_schemas) == 1:
                geom_key = next(iter(self.geometry_schemas.keys()))
                file_map[geom_key] = Path(files).resolve()
            else:
                raise ValueError(
                    f"Single file passed, but data_schema contains multiple geometries: "
                    f"{list(self.geometry_schemas.keys())}"
                )
        elif isinstance(files, Mapping):
            for k, f_path in files.items():
                if k not in self.geometry_schemas:
                    raise ValueError(f"Geometry '{k}' in files not defined in data_schema: {list(self.geometry_schemas.keys())}")
                file_map[k] = Path(f_path).resolve()
        else:
            raise TypeError(f"Invalid files type: {type(files).__name__}")

        parsed_geometries: dict[str, ParsedComsolGeometry] = {}
        for geom_name, f_path in file_map.items():
            g_schema = self.geometry_schemas[geom_name]
            coords_req = g_schema.get("coordinates", ["x", "y"])
            vars_req = g_schema.get("variables", {})

            transposed_flag = (
                transposed.get(geom_name)
                if isinstance(transposed, Mapping)
                else transposed
            )

            parser = get_parser_for_file(
                f_path,
                transposed=transposed_flag,
                alias_resolver=self.alias_resolver,
            )

            parsed_geometries[geom_name] = parser.parse(
                geometry_name=geom_name,
                coord_names=coords_req,
                variable_schema=vars_req,
                time_param=self.time_param,
            )

        ref_geom = next(iter(parsed_geometries.values()))
        n_steps = len(ref_geom.steps)
        for g_name, g_obj in parsed_geometries.items():
            if len(g_obj.steps) != n_steps:
                raise ValueError(
                    f"Geometry '{g_name}' step count ({len(g_obj.steps)}) does not match "
                    f"geometry '{ref_geom.geometry_name}' ({n_steps})"
                )

        dt = xr.DataTree()
        root_attrs = {
            "title": "COMSOL Parametric Simulation Dataset",
            "conventions": "CF-1.8",
            "source": "COMSOL Multiphysics",
            **self.data_schema.get("attrs", {}),
            **self.data_schema.get("root_attrs", {}),
        }
        dt.attrs = _sanitize_comsol_attrs(root_attrs)

        if self.time_param is None:
            self._build_steady_datatree(dt, parsed_geometries)
        else:
            self._build_transient_datatree(dt, parsed_geometries)

        return dt

    def _build_steady_datatree(
        self,
        dt: xr.DataTree,
        geometries: dict[str, ParsedComsolGeometry],
    ) -> None:
        """Assemble steady-state simulation sweep into xarray.DataTree."""
        ref_geom = next(iter(geometries.values()))

        for i, ref_step in enumerate(ref_geom.steps):
            step_idx = ref_step.step_index
            exp_name = self._format_exp_name(ref_step.parameters, step_idx, i + 1)
            exp_path = f"/{exp_name}"

            exp_vars = {}
            for target_name, param_key in self.top_vars.items():
                if param_key in ref_step.parameters:
                    val = ref_step.parameters[param_key]
                    unit = ref_step.param_units.get(param_key, "")
                    exp_vars[target_name] = xr.DataArray(
                        val,
                        attrs={"units": unit, "long_name": target_name},
                    )

            exp_ds = xr.Dataset(
                data_vars=exp_vars,
                attrs=_sanitize_comsol_attrs({
                    "step_index": step_idx,
                    **ref_step.parameters,
                }),
            )
            dt[exp_path] = xr.DataTree(dataset=exp_ds)

            for g_name, g_obj in geometries.items():
                g_step = g_obj.steps[i]
                g_vars = {}

                for v_name, arr in g_step.fields.items():
                    u = g_obj.field_units.get(v_name, "")
                    if arr.ndim == 1:
                        g_vars[v_name] = xr.DataArray(arr, dims=["node"], attrs={"units": u})
                    elif arr.ndim == 2:
                        g_vars[v_name] = xr.DataArray(
                            arr,
                            dims=["node", "spatial"],
                            coords={"spatial": g_obj.spatial_coords},
                            attrs={"units": u},
                        )

                coords_da = xr.DataArray(
                    g_obj.coordinates,
                    dims=["node", "spatial"],
                    coords={"spatial": g_obj.spatial_coords},
                    attrs={"units": "m"},
                )

                geom_ds = xr.Dataset(
                    data_vars=g_vars,
                    coords={"coordinates": coords_da, "spatial": g_obj.spatial_coords},
                )
                dt[f"{exp_path}/{g_name}"] = xr.DataTree(dataset=geom_ds)

    def _build_transient_datatree(
        self,
        dt: xr.DataTree,
        geometries: dict[str, ParsedComsolGeometry],
    ) -> None:
        """Assemble transient dynamic simulation sweep into xarray.DataTree."""
        ref_geom = next(iter(geometries.values()))

        exp_groups: dict[tuple[tuple[str, Any], ...], list[int]] = defaultdict(list)
        for i, step in enumerate(ref_geom.steps):
            exp_key = tuple(sorted(
                (k, v) for k, v in step.experiment_params.items()
                if k not in self.top_vars.values()
            ))
            exp_groups[exp_key].append(i)

        for run_idx, (exp_key, step_indices) in enumerate(exp_groups.items()):
            first_idx = step_indices[0]
            first_step = ref_geom.steps[first_idx]
            step_idx = first_step.step_index
            exp_name = self._format_exp_name(first_step.experiment_params, step_idx, run_idx + 1)
            exp_path = f"/{exp_name}"

            time_values = np.array(
                [ref_geom.steps[idx].time_value for idx in step_indices],
                dtype=np.float64,
            )
            time_da = xr.DataArray(time_values, dims=["time"], attrs={"units": "s"})

            exp_vars = {}
            for target_name, param_key in self.top_vars.items():
                vals = [ref_geom.steps[idx].parameters.get(param_key) for idx in step_indices]
                if any(v is not None for v in vals):
                    unit = first_step.param_units.get(param_key, "")
                    if len(set(vals)) > 1:
                        exp_vars[target_name] = xr.DataArray(
                            np.array(vals, dtype=np.float64),
                            dims=["time"],
                            attrs={"units": unit, "long_name": target_name},
                        )
                    else:
                        exp_vars[target_name] = xr.DataArray(
                            vals[0],
                            attrs={"units": unit, "long_name": target_name},
                        )

            exp_ds = xr.Dataset(
                data_vars=exp_vars,
                coords={"time": time_da},
                attrs=_sanitize_comsol_attrs({
                    "step_index": step_idx,
                    **first_step.experiment_params,
                }),
            )
            dt[exp_path] = xr.DataTree(dataset=exp_ds)

            for g_name, g_obj in geometries.items():
                g_vars = {}

                v_names = list(g_obj.steps[first_idx].fields.keys())
                for v_name in v_names:
                    stacked = np.stack(
                        [g_obj.steps[idx].fields[v_name] for idx in step_indices],
                        axis=0,
                    )
                    u = g_obj.field_units.get(v_name, "")
                    if stacked.ndim == 2:
                        g_vars[v_name] = xr.DataArray(stacked, dims=["time", "node"], attrs={"units": u})
                    elif stacked.ndim == 3:
                        g_vars[v_name] = xr.DataArray(
                            stacked,
                            dims=["time", "node", "spatial"],
                            coords={"spatial": g_obj.spatial_coords},
                            attrs={"units": u},
                        )

                coords_da = xr.DataArray(
                    g_obj.coordinates,
                    dims=["node", "spatial"],
                    coords={"spatial": g_obj.spatial_coords},
                    attrs={"units": "m"},
                )

                geom_ds = xr.Dataset(
                    data_vars=g_vars,
                    coords={"time": time_da, "coordinates": coords_da, "spatial": g_obj.spatial_coords},
                )
                dt[f"{exp_path}/{g_name}"] = xr.DataTree(dataset=geom_ds)

    def to_netcdf4(
        self,
        files: dict[str, str | Path] | str | Path,
        output_path: str | Path,
        transposed: dict[str, bool] | bool | None = None,
        complevel: int = 4,
        shuffle: bool = True,
    ) -> Path:
        """Convert geometry files and export directly to NetCDF-4."""
        out = Path(output_path).resolve()
        out.parent.mkdir(parents=True, exist_ok=True)

        dt = self.to_datatree(files, transposed=transposed)

        encoding: dict[str, Any] = {}
        for node in dt.subtree:
            group_encoding: dict[str, Any] = {}
            for v_name, da in node.dataset.data_vars.items():
                var_enc: dict[str, Any] = {
                    "zlib": True,
                    "complevel": complevel,
                    "shuffle": shuffle,
                }
                if "time" in da.dims:
                    t_idx = da.dims.index("time")
                    chunks = list(da.shape)
                    chunks[t_idx] = min(da.shape[t_idx], 100)
                    var_enc["chunksizes"] = tuple(chunks)
                elif "node" in da.dims:
                    n_idx = da.dims.index("node")
                    chunks = list(da.shape)
                    chunks[n_idx] = min(da.shape[n_idx], 5000)
                    var_enc["chunksizes"] = tuple(chunks)
                group_encoding[v_name] = var_enc
            if group_encoding:
                encoding[node.path] = group_encoding

        dt.to_netcdf(out, engine="h5netcdf", encoding=encoding)
        return out
