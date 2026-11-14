from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

import numpy as np
import xarray as xr
from tqdm import tqdm

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
        data_schema: dict[str, Any] | None = None,
        variables: list[str] | None = None,
        geometries: list[str] | None = None,
        parameters: list[str] | None = None,
        time_param: str | None = None,
        title: str | None = None,
        source: str | None = None,
        attrs: Mapping[str, Any] | None = None,
        exp_naming: str | Callable[[dict[str, Any], int], str] | None = "run_{step:03d}",
        custom_aliases: Mapping[str, str | list[str]] | None = None,
    ) -> None:
        self.data_schema = dict(data_schema) if data_schema else {}
        self.exp_naming = exp_naming
        self.alias_resolver = FieldAliasResolver(custom_aliases=custom_aliases)
        self.variables = list(variables) if variables else None
        self.geometries = list(geometries) if geometries else None
        self.parameters = list(parameters) if parameters else None
        self.time_param = self.data_schema.get("time", time_param)
        self.title = title
        self.source = source
        self.attrs = dict(attrs) if attrs else {}

        reserved = {
            "variables",
            "time",
            "title",
            "source",
            "attr",
            "attrs",
            "metadata",
            "root_attrs",
            "root_metadata",
        }
        self.top_vars: dict[str, str] = dict(self.data_schema.get("variables", {}))
        self.geometry_schemas: dict[str, dict[str, Any]] = {
            k: v for k, v in self.data_schema.items() if k not in reserved and isinstance(v, dict)
        }
        self.is_auto_schema = len(self.geometry_schemas) == 0

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
        files: Sequence[str | Path] | Mapping[str, str | Path] | str | Path,
        transposed: dict[str, bool] | bool | None = None,
    ) -> xr.DataTree:
        """Parse geometry files and construct an xarray.DataTree."""
        file_map: dict[str, Path] = {}

        if isinstance(files, (str, Path)):
            if not self.is_auto_schema:
                if len(self.geometry_schemas) == 1:
                    geom_key = next(iter(self.geometry_schemas.keys()))
                    file_map[geom_key] = Path(files).resolve()
                else:
                    raise ValueError(
                        f"Single file passed, but data_schema contains multiple geometries: "
                        f"{list(self.geometry_schemas.keys())}"
                    )
            else:
                if self.geometries:
                    if len(self.geometries) != 1:
                        raise ValueError(
                            f"Length of geometries ({len(self.geometries)}) must be 1 when a single file is passed."
                        )
                    geom_key = self.geometries[0]
                else:
                    geom_key = "geometry_1"
                file_map[geom_key] = Path(files).resolve()

        elif isinstance(files, Mapping):
            if self.geometries and len(self.geometries) != len(files):
                raise ValueError(
                    f"Length of geometries ({len(self.geometries)}) must match length of files ({len(files)})."
                )
            if not self.is_auto_schema:
                for k in files:
                    if k not in self.geometry_schemas:
                        raise ValueError(
                            f"Geometry '{k}' in files not defined in data_schema: {list(self.geometry_schemas.keys())}"
                        )
            file_map = {str(k): Path(f_path).resolve() for k, f_path in files.items()}

        elif isinstance(files, (list, tuple, Sequence)):
            n_files = len(files)
            if not self.is_auto_schema:
                if len(self.geometry_schemas) != n_files:
                    raise ValueError(
                        f"Length of data_schema geometries ({len(self.geometry_schemas)}) does not match length of files ({n_files})."
                    )
                geom_keys = list(self.geometry_schemas.keys())
            else:
                if self.geometries:
                    if len(self.geometries) != n_files:
                        raise ValueError(
                            f"Length of geometries ({len(self.geometries)}) does not match length of files ({n_files})."
                        )
                    geom_keys = list(self.geometries)
                else:
                    geom_keys = [f"geometry_{i+1}" for i in range(n_files)]
            file_map = {name: Path(f_path).resolve() for name, f_path in zip(geom_keys, files)}

        else:
            raise TypeError(f"Invalid files type: {type(files).__name__}")

        if self.is_auto_schema:
            for geom_name, f_path in file_map.items():
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
                f_coords, expressions, step_params, _ = parser.inspect()
                geom_vars: dict[str, str | list[str]] = {}
                consumed: set[str] = set()

                for v_name, v_comps in self.alias_resolver.custom_vector_aliases.items():
                    if all(c in expressions for c in v_comps):
                        geom_vars[v_name] = v_comps
                        consumed.update(v_comps)

                spatial_count = len(f_coords)
                vel_candidates = [
                    ["u", "v", "w"][:spatial_count],
                    ["vx", "vy", "vz"][:spatial_count],
                    ["ux", "uy", "uz"][:spatial_count],
                ]
                for cand in vel_candidates:
                    if all(c in expressions for c in cand) and not any(c in consumed for c in cand):
                        geom_vars["velocity"] = cand
                        consumed.update(cand)
                        break

                for expr in expressions:
                    if expr in consumed:
                        continue
                    canon = self.alias_resolver.resolve(expr)
                    target_name = canon if canon != expr else expr
                    geom_vars[target_name] = expr

                if self.variables:
                    filtered_vars: dict[str, str | list[str]] = {}
                    for v_req in self.variables:
                        matched = False
                        for t_name, spec in geom_vars.items():
                            if self.alias_resolver.matches(v_req, t_name) or (
                                isinstance(spec, str) and self.alias_resolver.matches(v_req, spec)
                            ):
                                filtered_vars[t_name] = spec
                                matched = True
                        if not matched and v_req in geom_vars:
                            filtered_vars[v_req] = geom_vars[v_req]
                    geom_vars = filtered_vars

                self.geometry_schemas[geom_name] = {
                    "coordinates": f_coords,
                    "variables": geom_vars,
                }

                if not self.top_vars:
                    if self.parameters:
                        for p_req in self.parameters:
                            matched = False
                            for p_key in step_params:
                                if self.alias_resolver.matches(p_req, p_key):
                                    self.top_vars[p_req] = p_key
                                    matched = True
                                    break
                            if not matched and p_req in step_params:
                                self.top_vars[p_req] = p_req
                    else:
                        for p_key in step_params:
                            if self.time_param and p_key == self.time_param:
                                continue
                            canon_p = self.alias_resolver.resolve(p_key)
                            self.top_vars[canon_p] = p_key

        parsed_geometries: dict[str, ParsedComsolGeometry] = {}
        for geom_name, f_path in tqdm(
            file_map.items(), desc="Parsing COMSOL geometries", unit="geometry", mininterval=0.5
        ):
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
            "title": self.title or self.data_schema.get("title", "COMSOL Parametric Simulation Dataset"),
            "conventions": "CF-1.8",
            "source": self.source or self.data_schema.get("source", "COMSOL Multiphysics"),
            **self.data_schema.get("attr", {}),
            **self.data_schema.get("attrs", {}),
            **self.data_schema.get("root_attrs", {}),
            **self.data_schema.get("metadata", {}),
            **self.attrs,
        }
        if "title" in self.data_schema.get("attrs", {}):
            root_attrs["title"] = self.data_schema["attrs"]["title"]
        elif "title" in self.data_schema.get("attr", {}):
            root_attrs["title"] = self.data_schema["attr"]["title"]

        if "source" in self.data_schema.get("attrs", {}):
            root_attrs["source"] = self.data_schema["attrs"]["source"]
        elif "source" in self.data_schema.get("attr", {}):
            root_attrs["source"] = self.data_schema["attr"]["source"]

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

        for i, ref_step in enumerate(
            tqdm(ref_geom.steps, desc="Assembling DataTree steps", unit="step", leave=False, mininterval=0.5)
        ):
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

        for run_idx, (exp_key, step_indices) in enumerate(
            tqdm(exp_groups.items(), desc="Assembling transient runs", unit="run", leave=False, mininterval=0.5)
        ):
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
        files: Sequence[str | Path] | Mapping[str, str | Path] | str | Path,
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
