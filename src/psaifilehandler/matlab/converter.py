from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import numpy as np
import xarray as xr

from .mat_file import MATFile


def parse_metadata_file(filepath: str | Path) -> dict[str, str]:
    """Read metadata file as a raw text string keyed by its filename with extension."""
    path = Path(filepath).resolve()
    if not path.exists():
        raise FileNotFoundError(f"Metadata file not found: {path}")
    return {path.name: path.read_text(encoding="utf-8", errors="replace")}


def sanitize_attrs(attrs: Mapping[str, Any]) -> dict[str, Any]:
    """Sanitize dictionary values into NetCDF-4 compatible attribute types."""
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
            elif all(isinstance(x, str) for x in v):
                clean[str(k)] = list(v)
            else:
                clean[str(k)] = json.dumps(v)
        elif isinstance(v, dict):
            clean[str(k)] = json.dumps(v)
        elif isinstance(v, np.ndarray):
            clean[str(k)] = v if v.ndim == 1 else v.tolist()
        else:
            clean[str(k)] = str(v)
    return clean


def load_metadata(source: str | Path | Mapping[str, Any] | Sequence[Any] | None) -> dict[str, Any]:
    """Load metadata from file paths, mappings, sequences, or callables into attribute dictionaries."""
    if callable(source):
        source = source()
    if source is None:
        return {}
    if isinstance(source, Mapping):
        return sanitize_attrs(source)
    if isinstance(source, (str, Path)):
        p = Path(source)
        if p.exists() and p.is_file():
            return parse_metadata_file(p)
        return {"metadata.txt": str(source)}
    if isinstance(source, Sequence) and not isinstance(source, str):
        combined = {}
        for item in source:
            combined.update(load_metadata(item))
        return combined
    return {"metadata.txt": str(source)}


def normalize_variable(
    var_name: str,
    var_data: Any,
    n_nodes: int | None = None,
    n_times: int | None = None,
    n_spatial: int | None = None,
    spatial_coords: list[str] | None = None,
) -> xr.DataArray:
    """Normalize input variable data into xarray.DataArray adhering to standard simulation dimensions."""
    attrs = {}
    if isinstance(var_data, xr.DataArray):
        attrs = dict(var_data.attrs)
        if var_data.dims in (("time", "node"), ("node",), ("time", "node", "spatial"), ("node", "spatial"), ("time",)):
            return var_data
        arr = np.array(var_data.values, copy=True)
    elif hasattr(var_data, "to_numpy"):
        arr = np.array(var_data.to_numpy(), copy=True)
    else:
        arr = np.array(var_data, copy=True)

    ndim = arr.ndim
    default_spatial = spatial_coords or (["x", "y", "z"][:n_spatial] if n_spatial in (2, 3) else [f"dim_{i}" for i in range(arr.shape[-1])])

    if ndim == 1:
        if n_times is not None and len(arr) == n_times:
            if n_nodes == 1:
                return xr.DataArray(arr[:, None], dims=["time", "node"], attrs=attrs)
            return xr.DataArray(arr, dims=["time"], attrs=attrs)
        return xr.DataArray(arr, dims=["node"], attrs=attrs)

    if ndim == 2:
        if n_times is not None and n_nodes is not None:
            if arr.shape == (n_times, n_nodes):
                return xr.DataArray(arr, dims=["time", "node"], attrs=attrs)
            if arr.shape == (n_nodes, n_times):
                return xr.DataArray(arr.T, dims=["time", "node"], attrs=attrs)

        if n_nodes is not None and arr.shape[0] == n_nodes and arr.shape[1] in (2, 3):
            return xr.DataArray(arr, dims=["node", "spatial"], coords={"spatial": default_spatial}, attrs=attrs)

        if n_times is not None:
            if arr.shape[0] == n_times:
                return xr.DataArray(arr, dims=["time", "node"], attrs=attrs)
            if arr.shape[1] == n_times:
                return xr.DataArray(arr.T, dims=["time", "node"], attrs=attrs)

        if arr.shape[1] in (2, 3) and (n_nodes is None or arr.shape[0] == n_nodes):
            return xr.DataArray(arr, dims=["node", "spatial"], coords={"spatial": default_spatial}, attrs=attrs)

        return xr.DataArray(arr, dims=["time", "node"], attrs=attrs)

    if ndim == 3:
        if n_times is not None and n_nodes is not None and arr.shape[0] == n_nodes and arr.shape[1] == n_times:
            arr = np.transpose(arr, (1, 0, 2))
        return xr.DataArray(arr, dims=["time", "node", "spatial"], coords={"spatial": default_spatial}, attrs=attrs)

    raise ValueError(f"Unsupported array dimensionality {ndim} for variable '{var_name}' (shape={arr.shape})")


def _build_dataset_from_dict(
    spec_dict: dict[str, Any],
    extra_attrs: dict[str, Any] | None = None,
) -> xr.Dataset:
    """Build an xarray.Dataset from a mesh or experiment specification dictionary."""
    metadata = {}
    for mkey in ("metadata", "attrs", "mesh_metadata"):
        if mkey in spec_dict:
            metadata.update(load_metadata(spec_dict[mkey]))
    if extra_attrs:
        metadata.update(extra_attrs)

    coords_dict: dict[str, Any] = {}
    n_nodes, n_spatial, n_times = None, None, None
    spatial_labels = None

    raw_coords = spec_dict.get("coordinates")
    if callable(raw_coords):
        raw_coords = raw_coords()

    if raw_coords is not None:
        if isinstance(raw_coords, xr.DataArray):
            coords_arr = np.array(raw_coords.values, copy=True)
            if "spatial" in raw_coords.coords:
                spatial_labels = list(raw_coords.coords["spatial"].values)
            elif "col" in raw_coords.coords:
                raw_labels = [str(c) for c in raw_coords.coords["col"].values]
                if any(lbl.startswith("Var") or "_X" in lbl for lbl in raw_labels) and len(raw_labels) in (2, 3):
                    spatial_labels = ["x", "y", "z"][:len(raw_labels)]
                else:
                    spatial_labels = raw_labels
        elif hasattr(raw_coords, "to_numpy"):
            coords_arr = np.array(raw_coords.to_numpy(), copy=True)
        else:
            coords_arr = np.array(raw_coords, copy=True)

        if coords_arr.ndim != 2:
            raise ValueError(f"Coordinates array must have 2 dimensions (node, spatial), got shape {coords_arr.shape}")

        n_nodes, n_spatial = coords_arr.shape
        if spatial_labels is None or len(spatial_labels) != n_spatial:
            spatial_labels = ["x", "y", "z"][:n_spatial] if n_spatial in (2, 3) else [f"dim_{i}" for i in range(n_spatial)]

        coords_dict["coordinates"] = xr.DataArray(
            coords_arr,
            dims=["node", "spatial"],
            coords={"spatial": spatial_labels},
        )
        coords_dict["spatial"] = spatial_labels

    raw_time = spec_dict.get("time")
    if callable(raw_time):
        raw_time = raw_time()

    if raw_time is not None:
        time_arr = np.array(
            raw_time.values if isinstance(raw_time, xr.DataArray)
            else (raw_time.to_numpy() if hasattr(raw_time, "to_numpy") else raw_time),
            copy=True,
        )
        if time_arr.ndim != 1:
            time_arr = time_arr.ravel()
        n_times = len(time_arr)
        coords_dict["time"] = xr.DataArray(time_arr, dims=["time"])

    variables_dict = spec_dict.get("variables", {})
    resolved_vars = {k: (v() if callable(v) else v) for k, v in variables_dict.items()}

    if n_times is None and n_nodes is not None:
        for vdata in resolved_vars.values():
            if isinstance(vdata, xr.DataArray) and "col" in vdata.coords:
                c_vals = list(vdata.coords["col"].values)
                if "time" in c_vals and len(c_vals) == n_nodes + 1:
                    extracted_time = vdata.sel(col="time").values
                    n_times = len(extracted_time)
                    coords_dict["time"] = xr.DataArray(extracted_time, dims=["time"])
                    break

    norm_variables = {}
    for var_name, var_data in resolved_vars.items():
        clean_vdata = var_data
        if n_nodes is not None and isinstance(var_data, xr.DataArray) and "col" in var_data.coords:
            c_vals = list(var_data.coords["col"].values)
            if "time" in c_vals and len(c_vals) == n_nodes + 1:
                clean_vdata = var_data.sel(col=[c for c in c_vals if c != "time"])

        norm_var = normalize_variable(
            var_name=var_name,
            var_data=clean_vdata,
            n_nodes=n_nodes,
            n_times=n_times,
            n_spatial=n_spatial,
            spatial_coords=spatial_labels,
        )
        clean_var_name = var_name.replace("/", "_")
        if clean_var_name != var_name and "original_name" not in norm_var.attrs:
            norm_var.attrs["original_name"] = var_name
        norm_variables[clean_var_name] = norm_var

    return xr.Dataset(
        data_vars=norm_variables,
        coords=coords_dict,
        attrs=sanitize_attrs(metadata),
    )


def build_datatree(
    mapping: dict[str, Any],
    root_attrs: dict[str, Any] | None = None,
    root_metadata: str | Path | dict | None = None,
    single_mesh: bool = False,
    flat: bool = False,
) -> xr.DataTree:
    """Build a hierarchical xarray.DataTree from a declarative mapping dictionary."""
    dt = xr.DataTree()
    is_flat = single_mesh or flat

    combined_root_attrs = {}
    if root_metadata is not None:
        combined_root_attrs.update(load_metadata(root_metadata))
    if root_attrs is not None:
        combined_root_attrs.update(sanitize_attrs(root_attrs))

    for rkey in ("metadata", "root_metadata", "attrs", "root_attrs"):
        if rkey in mapping:
            combined_root_attrs.update(load_metadata(mapping[rkey]))

    dt.attrs = sanitize_attrs(combined_root_attrs)

    reserved_root_keys = {"metadata", "root_metadata", "attrs", "root_attrs"}
    experiment_keys = [k for k in mapping.keys() if k not in reserved_root_keys]

    for exp_name in experiment_keys:
        exp_dict = mapping[exp_name]
        if not isinstance(exp_dict, dict):
            continue

        exp_node_path = f"/{exp_name}"
        exp_metadata = {}
        for mkey in ("metadata", "attrs"):
            if mkey in exp_dict:
                exp_metadata.update(load_metadata(exp_dict[mkey]))

        reserved_exp_keys = {"metadata", "attrs", "variables", "coordinates", "time"}
        mesh_keys = [k for k in exp_dict.keys() if k not in reserved_exp_keys]

        if not mesh_keys and "variables" in exp_dict:
            dt[exp_node_path] = _build_dataset_from_dict(exp_dict, extra_attrs=exp_metadata)
            continue

        if is_flat:
            if len(mesh_keys) == 1:
                mesh_name = mesh_keys[0]
                dt[exp_node_path] = _build_dataset_from_dict(exp_dict[mesh_name], extra_attrs=exp_metadata)
                continue
            if len(mesh_keys) > 1:
                raise ValueError(f"single_mesh/flat=True requested, but experiment '{exp_name}' contains multiple meshes: {mesh_keys}")

        if "variables" in exp_dict:
            exp_dataset = _build_dataset_from_dict(
                {k: exp_dict[k] for k in ("variables", "time", "coordinates") if k in exp_dict},
                extra_attrs=exp_metadata,
            )
            dt[exp_node_path] = xr.DataTree(dataset=exp_dataset)
        else:
            if exp_node_path not in dt:
                dt[exp_node_path] = xr.DataTree()
            dt[exp_node_path].attrs.update(sanitize_attrs(exp_metadata))

        for mesh_name in mesh_keys:
            if isinstance(exp_dict[mesh_name], dict):
                dt[f"/{exp_name}/{mesh_name}"] = _build_dataset_from_dict(exp_dict[mesh_name])

    return dt


def mat_to_netcdf4(
    mapping: dict[str, Any],
    output_path: str | Path | None = None,
    root_attrs: dict[str, Any] | None = None,
    root_metadata: str | Path | dict | None = None,
    single_mesh: bool = False,
    flat: bool = False,
    engine: str = "h5netcdf",
    **kwargs: Any,
) -> xr.DataTree | Path:
    """Map parsed MATLAB data into a hierarchical NetCDF-4 file or xarray.DataTree."""
    tree = build_datatree(
        mapping,
        root_attrs=root_attrs,
        root_metadata=root_metadata,
        single_mesh=single_mesh,
        flat=flat,
    )

    if output_path is not None:
        out = Path(output_path).resolve()
        out.parent.mkdir(parents=True, exist_ok=True)
        tree.to_netcdf(str(out), engine=engine, **kwargs)
        print(f"Successfully exported NetCDF-4 to: {out}")
        return out

    return tree


class MATConverter:
    """General NetCDF-4 / DataTree converter for MATLAB datasets."""

    mat_file: MATFile

    def __init__(self, mat_file_or_path: MATFile | str | Path, **kwargs: Any) -> None:
        if isinstance(mat_file_or_path, MATFile):
            self.mat_file = mat_file_or_path
        else:
            self.mat_file = MATFile(mat_file_or_path, **kwargs)

    def read(self, preload: bool = False, max_elements: int | None = None) -> dict[str, Any]:
        """Read data variables from the owned MATFile."""
        return self.mat_file.read(preload=preload, max_elements=max_elements)

    def build_datatree(
        self,
        mapping: dict[str, Any],
        root_attrs: dict[str, Any] | None = None,
        root_metadata: str | Path | dict | None = None,
        single_mesh: bool = False,
        flat: bool = False,
    ) -> xr.DataTree:
        """Construct an xarray.DataTree from an explicit hierarchy mapping."""
        return build_datatree(
            mapping,
            root_attrs=root_attrs,
            root_metadata=root_metadata,
            single_mesh=single_mesh,
            flat=flat,
        )

    def to_netcdf4(
        self,
        mapping: dict[str, Any],
        output_path: str | Path,
        root_attrs: dict[str, Any] | None = None,
        root_metadata: str | Path | dict | None = None,
        single_mesh: bool = False,
        flat: bool = False,
        engine: str = "h5netcdf",
        **kwargs: Any,
    ) -> Path:
        """Convert mapping dictionary to NetCDF-4 using h5netcdf or netcdf4 engine."""
        result = mat_to_netcdf4(
            mapping,
            output_path=output_path,
            root_attrs=root_attrs,
            root_metadata=root_metadata,
            single_mesh=single_mesh,
            flat=flat,
            engine=engine,
            **kwargs,
        )
        return Path(result)

    def close(self) -> None:
        """Close the owned MATFile engine."""
        self.mat_file.close()

    def __enter__(self) -> MATConverter:
        self.mat_file.__enter__()
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.mat_file.__exit__(exc_type, exc_val, exc_tb)

    def __repr__(self) -> str:
        return f"<MATConverter mat_file={self.mat_file!r}>"
