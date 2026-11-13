from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

import numpy as np
import xarray as xr

from .accessors import PathAccessor, compile_accessor, evaluate_accessor
from .converter import MATConverter
from .mat_file import MATFile


def _normalize_mesh_schema(
    mesh_schema: dict[str, Any] | Sequence[str],
    coord_path: str | None,
    time_path: str | None,
    is_flat: bool,
) -> tuple[dict[str, dict[str, Any]], bool]:
    """Normalize input mesh schema into a standardized dictionary of mesh specifications."""
    parsed: dict[str, dict[str, Any]] = {}

    if isinstance(mesh_schema, Sequence) and not isinstance(mesh_schema, (str, Mapping)):
        parsed["mesh_1"] = {
            "coordinates": compile_accessor(coord_path),
            "time": compile_accessor(time_path),
            "variables": {str(v): compile_accessor(v) for v in mesh_schema},
            "metadata": None,
        }
        return parsed, True

    if not isinstance(mesh_schema, dict):
        raise TypeError(f"Invalid mesh_schema type: {type(mesh_schema).__name__}")

    if "variables" in mesh_schema:
        raw_vars = mesh_schema["variables"]
        v_dict = (
            {k: compile_accessor(v) for k, v in raw_vars.items()}
            if isinstance(raw_vars, Mapping)
            else {str(v): compile_accessor(v) for v in raw_vars}
        )
        c_acc = compile_accessor(
            mesh_schema.get("coordinates")
            or mesh_schema.get("coord_path")
            or mesh_schema.get("coord_key")
            or coord_path
        )
        t_acc = compile_accessor(
            mesh_schema.get("time")
            or mesh_schema.get("time_path")
            or mesh_schema.get("time_key")
            or time_path
        )
        parsed["mesh_1"] = {
            "coordinates": c_acc,
            "time": t_acc,
            "variables": v_dict,
            "metadata": mesh_schema.get("metadata"),
        }
        return parsed, True

    if all(not isinstance(v, Mapping) for v in mesh_schema.values()) and (
        is_flat or all(isinstance(v, (str, PathAccessor)) or callable(v) for v in mesh_schema.values())
    ):
        parsed["mesh_1"] = {
            "coordinates": compile_accessor(coord_path),
            "time": compile_accessor(time_path),
            "variables": {k: compile_accessor(v) for k, v in mesh_schema.items()},
            "metadata": None,
        }
        return parsed, True

    for m_name, m_spec in mesh_schema.items():
        if isinstance(m_spec, Mapping):
            raw_vars = m_spec.get("variables", {})
            v_dict = (
                {k: compile_accessor(v) for k, v in raw_vars.items()}
                if isinstance(raw_vars, Mapping)
                else {str(v): compile_accessor(v) for v in raw_vars}
            )
            c_acc = compile_accessor(
                m_spec.get("coordinates")
                or m_spec.get("coord_path")
                or m_spec.get("coord_key")
                or coord_path
            )
            t_acc = compile_accessor(
                m_spec.get("time")
                or m_spec.get("time_path")
                or m_spec.get("time_key")
                or time_path
            )
            parsed[m_name] = {
                "coordinates": c_acc,
                "time": t_acc,
                "variables": v_dict,
                "metadata": m_spec.get("metadata"),
            }
        elif isinstance(m_spec, Sequence) and not isinstance(m_spec, str):
            parsed[m_name] = {
                "coordinates": compile_accessor(coord_path),
                "time": compile_accessor(time_path),
                "variables": {str(v): compile_accessor(v) for v in m_spec},
                "metadata": None,
            }
        else:
            raise TypeError(f"Invalid schema specification for mesh '{m_name}': {type(m_spec).__name__}")

    if is_flat and len(parsed) != 1:
        raise ValueError(
            f"single_mesh/flat=True was specified, but mesh_schema contains {len(parsed)} meshes: "
            f"{list(parsed.keys())}. single_mesh=True only supports exactly one mesh."
        )

    return parsed, is_flat


def _validate_sweep_invariance(
    mat_struct: Sequence[Any],
    parsed_schema: dict[str, dict[str, Any]],
    global_coords: Any | None,
    global_time: Any | None,
    validate_all: bool,
    coord_atol: float = 1e-8,
) -> None:
    """Validate paths on mat_struct[0] and assert shape and coordinate invariance across all runs."""
    expected_shapes: dict[tuple[str, str], tuple[int, ...]] = {}
    expected_coords: dict[str, np.ndarray] = {}
    runs_to_check = len(mat_struct) if validate_all else 1

    for i in range(runs_to_check):
        elem = mat_struct[i]
        exp_id_str = f"index {i}" + (f" ('{elem.name}')" if hasattr(elem, "name") and elem.name else "")

        for m_name, m_info in parsed_schema.items():
            c_acc = m_info["coordinates"]
            has_global_c = global_coords is not None and (
                isinstance(global_coords, Mapping) and m_name in global_coords or not isinstance(global_coords, Mapping)
            )
            if not has_global_c and c_acc is not None:
                try:
                    c_val = evaluate_accessor(c_acc, elem)
                except (AttributeError, KeyError) as e:
                    expr = getattr(c_acc, "expr", c_acc)
                    prefix = "Initialization validation failed on mat_struct[0]" if i == 0 else f"Experiment {exp_id_str} breaks invariance"
                    raise type(e)(f"{prefix} for mesh '{m_name}' coordinates path '{expr}': {e}") from e

                if hasattr(c_val, "shape"):
                    if i == 0:
                        expected_shapes[(m_name, "__coordinates__")] = c_val.shape
                        expected_coords[m_name] = np.asanyarray(c_val)
                    else:
                        exp_s = expected_shapes.get((m_name, "__coordinates__"))
                        if exp_s is not None and c_val.shape != exp_s:
                            raise ValueError(
                                f"Experiment {exp_id_str} breaks shape invariance for mesh '{m_name}' coordinates: "
                                f"expected shape {exp_s}, got {c_val.shape}"
                            )
                        ref_c = expected_coords.get(m_name)
                        if ref_c is not None and not np.allclose(np.asanyarray(c_val), ref_c, atol=coord_atol):
                            raise ValueError(
                                f"Experiment {exp_id_str} breaks spatial coordinate invariance for mesh '{m_name}' "
                                f"(atol={coord_atol})"
                            )

            t_acc = m_info["time"]
            if global_time is None and t_acc is not None:
                try:
                    t_val = evaluate_accessor(t_acc, elem)
                except (AttributeError, KeyError) as e:
                    expr = getattr(t_acc, "expr", t_acc)
                    prefix = "Initialization validation failed on mat_struct[0]" if i == 0 else f"Experiment {exp_id_str} breaks invariance"
                    raise type(e)(f"{prefix} for mesh '{m_name}' time path '{expr}': {e}") from e

                if i == 0 and hasattr(t_val, "shape"):
                    expected_shapes[(m_name, "__time__")] = t_val.shape
                elif i > 0 and hasattr(t_val, "shape"):
                    exp_s = expected_shapes.get((m_name, "__time__"))
                    if exp_s is not None and t_val.shape != exp_s:
                        raise ValueError(
                            f"Experiment {exp_id_str} breaks shape invariance for mesh '{m_name}' time: "
                            f"expected shape {exp_s}, got {t_val.shape}"
                        )

            for v_name, v_acc in m_info["variables"].items():
                try:
                    v_val = evaluate_accessor(v_acc, elem)
                except (AttributeError, KeyError) as e:
                    expr = getattr(v_acc, "expr", v_acc)
                    prefix = "Initialization validation failed on mat_struct[0]" if i == 0 else f"Experiment {exp_id_str} breaks invariance"
                    raise type(e)(f"{prefix} for mesh '{m_name}', variable '{v_name}' path '{expr}': {e}") from e

                if i == 0 and hasattr(v_val, "shape"):
                    expected_shapes[(m_name, v_name)] = v_val.shape
                elif i > 0 and hasattr(v_val, "shape"):
                    exp_s = expected_shapes.get((m_name, v_name))
                    if exp_s is not None and v_val.shape != exp_s:
                        raise ValueError(
                            f"Experiment {exp_id_str} breaks shape invariance for mesh '{m_name}', variable '{v_name}': "
                            f"expected shape {exp_s}, got {v_val.shape}"
                        )


def _resolve_exp_name(elem: Any, idx: int, naming: str | Callable[[Any, int], str] | None) -> str:
    """Resolve clean experiment group name from element reference and index."""
    if callable(naming):
        return naming(elem, idx)
    if isinstance(naming, str):
        ctx = {"i": idx, "index": idx + 1, "name": getattr(elem, "name", f"run_{idx}"), "id": getattr(elem, "id", f"run_{idx}")}
        return naming.format(**ctx)
    if hasattr(elem, "name") and elem.name:
        return str(elem.name).strip()
    if hasattr(elem, "id") and elem.id:
        return f"experiment_{elem.id}"
    return f"experiment_{idx + 1}"


def _build_mesh_entry(
    m_name: str,
    m_info: dict[str, Any],
    i: int,
    mat_struct: Sequence[Any],
    global_coords: Any | None,
    global_time: Any | None,
    meta_dir_path: Path | None,
    mesh_template: str,
    exp_name: str,
) -> dict[str, Any]:
    """Build a mesh specification dictionary with deferred accessors."""
    mesh_dict: dict[str, Any] = {}

    if m_info.get("metadata") is not None:
        mesh_dict["metadata"] = m_info["metadata"]
    elif meta_dir_path is not None:
        meta_file = meta_dir_path / mesh_template.format(mesh_name=m_name, exp_name=exp_name, i=i)
        if meta_file.exists():
            mesh_dict["metadata"] = meta_file

    if global_coords is not None:
        mesh_dict["coordinates"] = global_coords[m_name] if isinstance(global_coords, Mapping) and m_name in global_coords else global_coords
    elif m_info["coordinates"] is not None:
        c_acc = m_info["coordinates"]
        mesh_dict["coordinates"] = lambda idx=i, acc=c_acc: evaluate_accessor(acc, mat_struct[idx])

    if global_time is not None:
        mesh_dict["time"] = global_time
    elif m_info["time"] is not None:
        t_acc = m_info["time"]
        mesh_dict["time"] = lambda idx=i, acc=t_acc: evaluate_accessor(acc, mat_struct[idx])

    mesh_dict["variables"] = {
        v_name: (lambda idx=i, acc=v_acc: evaluate_accessor(acc, mat_struct[idx]))
        for v_name, v_acc in m_info["variables"].items()
    }

    return mesh_dict


def build_structured_sweep_mapping(
    mat_struct: Sequence[Any],
    mesh_schema: dict[str, Any] | Sequence[str],
    time_path: str | None = None,
    coord_path: str | None = None,
    coord_key: str | None = None,
    time_key: str | None = None,
    global_coords: Any | None = None,
    global_time: Any | None = None,
    metadata_dir: str | Path | None = None,
    metadata_naming: dict[str, str] | None = None,
    exp_naming: str | Callable[[Any, int], str] | None = None,
    validate_invariance: bool = True,
    single_mesh: bool = False,
    flat: bool = False,
    root_metadata: str | Path | Mapping[str, Any] | None = None,
    root_attrs: Mapping[str, Any] | None = None,
    coord_atol: float = 1e-8,
) -> dict[str, Any]:
    """Construct a declarative mapping dictionary for structured simulation sweeps using accessor paths."""
    num_experiments = len(mat_struct)
    if num_experiments == 0:
        raise ValueError("mat_struct is empty; cannot build sweep mapping.")

    if mesh_schema is None:
        raise ValueError("mesh_schema is required. Please provide a schema mapping component meshes to variables.")

    effective_coord = coord_path if coord_path is not None else coord_key
    effective_time = time_path if time_path is not None else time_key
    parsed_schema, is_flat = _normalize_mesh_schema(mesh_schema, effective_coord, effective_time, single_mesh or flat)

    _validate_sweep_invariance(
        mat_struct,
        parsed_schema,
        global_coords,
        global_time,
        validate_invariance and num_experiments > 1,
        coord_atol=coord_atol,
    )

    meta_dir_path = Path(metadata_dir).resolve() if metadata_dir is not None else None
    naming_map = metadata_naming or {}
    exp_template = naming_map.get("experiment", "{exp_name}_conditions.csv")
    mesh_template = naming_map.get("mesh", "{mesh_name}_properties.txt")

    mapping: dict[str, Any] = {}
    if root_metadata is not None:
        mapping["root_metadata"] = root_metadata
    if root_attrs is not None:
        mapping["root_attrs"] = root_attrs

    for i in range(num_experiments):
        elem_ref = mat_struct[i]
        exp_name = _resolve_exp_name(elem_ref, i, exp_naming)
        exp_dict: dict[str, Any] = {}

        if meta_dir_path is not None:
            exp_meta = meta_dir_path / exp_template.format(exp_name=exp_name, i=i, index=i + 1, name=getattr(elem_ref, "name", exp_name))
            if exp_meta.exists():
                exp_dict["metadata"] = exp_meta

        if is_flat:
            m_name, m_info = next(iter(parsed_schema.items()))
            entry = _build_mesh_entry(m_name, m_info, i, mat_struct, global_coords, global_time, meta_dir_path, mesh_template, exp_name)
            if "metadata" in entry:
                exp_dict["mesh_metadata"] = entry.pop("metadata")
            exp_dict.update(entry)
        else:
            for m_name, m_info in parsed_schema.items():
                exp_dict[m_name] = _build_mesh_entry(m_name, m_info, i, mat_struct, global_coords, global_time, meta_dir_path, mesh_template, exp_name)

        mapping[exp_name] = exp_dict

    return mapping


class MATSweepConverter:
    """Declarative simulation sweep converter leveraging composition with MATConverter."""

    converter: MATConverter

    def __init__(
        self,
        converter_or_source: MATConverter | MATFile | str | Path,
        **kwargs: Any,
    ) -> None:
        if isinstance(converter_or_source, MATConverter):
            self.converter = converter_or_source
        elif isinstance(converter_or_source, MATFile):
            self.converter = MATConverter(converter_or_source)
        else:
            self.converter = MATConverter(converter_or_source, **kwargs)

    @property
    def mat_file(self) -> MATFile:
        """Access the underlying MATFile instance."""
        return self.converter.mat_file

    def build_sweep_mapping(
        self,
        mat_struct: Sequence[Any],
        mesh_schema: dict[str, Any] | Sequence[str],
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Construct a declarative mapping dictionary for structured simulation sweeps."""
        return build_structured_sweep_mapping(mat_struct, mesh_schema, **kwargs)

    def convert(
        self,
        mat_struct: Sequence[Any],
        mesh_schema: dict[str, Any] | Sequence[str],
        output_path: str | Path | None = None,
        root_attrs: dict[str, Any] | None = None,
        root_metadata: str | Path | dict | None = None,
        single_mesh: bool = False,
        flat: bool = False,
        engine: str = "h5netcdf",
        coord_atol: float = 1e-8,
        **sweep_kwargs: Any,
    ) -> xr.DataTree | Path:
        """Build declarative mapping and convert sweep directly to DataTree or NetCDF-4."""
        mapping = self.build_sweep_mapping(
            mat_struct=mat_struct,
            mesh_schema=mesh_schema,
            root_attrs=root_attrs,
            root_metadata=root_metadata,
            single_mesh=single_mesh,
            flat=flat,
            coord_atol=coord_atol,
            **sweep_kwargs,
        )

        if output_path is not None:
            return self.converter.to_netcdf4(
                mapping=mapping,
                output_path=output_path,
                engine=engine,
                single_mesh=single_mesh,
                flat=flat,
            )

        return self.converter.build_datatree(
            mapping=mapping,
            root_attrs=root_attrs,
            root_metadata=root_metadata,
            single_mesh=single_mesh,
            flat=flat,
        )

    def to_netcdf4(self, mapping: dict[str, Any], output_path: str | Path, **kwargs: Any) -> Path:
        """Facade forwarding to internal converter."""
        return self.converter.to_netcdf4(mapping, output_path, **kwargs)

    def build_datatree(self, mapping: dict[str, Any], **kwargs: Any) -> xr.DataTree:
        """Facade forwarding to internal converter."""
        return self.converter.build_datatree(mapping, **kwargs)

    def read(self, preload: bool = False, max_elements: int | None = None) -> dict[str, Any]:
        """Facade forwarding to internal converter."""
        return self.converter.read(preload=preload, max_elements=max_elements)

    def close(self) -> None:
        """Facade forwarding to internal converter."""
        self.converter.close()

    def __enter__(self) -> MATSweepConverter:
        self.converter.__enter__()
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.converter.__exit__(exc_type, exc_val, exc_tb)

    def __repr__(self) -> str:
        return f"<MATSweepConverter converter={self.converter!r}>"
