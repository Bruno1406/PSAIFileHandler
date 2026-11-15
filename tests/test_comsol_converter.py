from __future__ import annotations

from pathlib import Path

import numpy as np
import xarray as xr

from psaifilehandler.comsol import (
    ComsolConverter,
    FieldAliasResolver,
    parse_expression_header,
)


def test_comsol_header_parsing() -> None:
    """Verify parsing of COMSOL header strings and parameter extraction."""
    # Standard format header segment
    txt_header = "u (m/s) @ 1: Q_in=0.1 m^3/h, rot_rpm=1000 rpm"
    p1 = parse_expression_header(txt_header)
    assert p1.expression == "u"
    assert p1.units == "m/s"
    assert p1.step_index == 1
    assert p1.parameters["Q_in"] == 0.1
    assert p1.parameters["rot_rpm"] == 1000
    assert p1.param_units["Q_in"] == "m^3/h"
    assert p1.param_units["rot_rpm"] == "rpm"

    # VTU format header
    vtu_header = "Velocity_field,_x_component_@_1:_Q_in=0.1_m^3/h,_rot_rpm=1000_rpm"
    p2 = parse_expression_header(vtu_header)
    assert p2.expression == "Velocity field, x component"
    assert p2.step_index == 1
    assert p2.parameters["Q_in"] == 0.1
    assert p2.parameters["rot_rpm"] == 1000

    # Transient parameters with scientific notation
    trn_header = "p (Pa) @ 6: Time=5E-4 s, rot_rpm=1000 rpm, Q_in=4 m^3/h"
    p3 = parse_expression_header(trn_header)
    assert p3.expression == "p"
    assert p3.units == "Pa"
    assert p3.step_index == 6
    assert p3.parameters["Time"] == 0.0005


def test_comsol_alias_resolver() -> None:
    """Verify canonical alias matching, descriptive name normalization, and custom overrides."""
    resolver = FieldAliasResolver(custom_aliases={"custom_var": "vx"})

    # Canonical default aliases
    assert resolver.resolve("u") == "vx"
    assert resolver.resolve("p") == "pressure"
    assert resolver.resolve("v") == "vy"
    assert resolver.resolve("w") == "vz"
    assert resolver.resolve("alphat") == "alphat"
    assert resolver.resolve("rotation_angle") == "alphat"

    # Multi-word descriptive strings and regex variations
    assert resolver.resolve("Velocity_field,_x_component") == "vx"
    assert resolver.resolve("Velocity field, y component") == "vy"
    assert resolver.resolve("Velocity_field,z_component") == "vz"
    assert resolver.resolve("velocity x") == "vx"
    assert resolver.resolve("u_comp1") == "vx"
    assert resolver.resolve("Total_traction,_exterior_boundaries,_x_component") == "t_tracx"
    assert resolver.resolve("Total_traction,_exterior_boundaries,_z_component") == "t_tracz"
    assert resolver.resolve("Pressure") == "pressure"
    assert resolver.resolve("static_pressure") == "pressure"
    assert resolver.resolve("Rotation_angle") == "alphat"

    # Custom override
    assert resolver.resolve("custom_var") == "vx"

    # Matching logic
    assert resolver.matches("u", "Velocity_field,_x_component")
    assert resolver.matches("pressure", "p")
    assert resolver.matches("p", "Pressure")


def test_comsol_format_parity_mrf() -> None:
    """Assert 100% numerical parity across .txt, _Transpose.txt, and .vtu MRF exports."""
    schema = {
        "variables": {
            "Volumetric Flux": "Q_in",
            "Rotational Speed": "rot_rpm",
        },
        "inlet": {
            "coordinates": ["x", "y"],
            "variables": {
                "velocity": ["u", "v"],
                "pressure": "p",
            },
        },
    }

    converter = ComsolConverter(data_schema=schema)

    # 1. Ingest standard flat TXT
    dt_flat = converter.to_datatree("data/comsol/Pump2D_MRFStudy_UltraFine_Inlet.txt")

    # 2. Ingest transposed TXT
    dt_trans = converter.to_datatree("data/comsol/Pump2D_MRFStudy_UltraFine_Inlet_Transpose.txt")

    # 3. Ingest VTU
    dt_vtu = converter.to_datatree("data/comsol/Pump2D_MRFStudy_UltraFine_Inlet.vtu")

    assert len(dt_flat.children) == 2337
    assert len(dt_trans.children) == 2337
    assert len(dt_vtu.children) == 2337

    first_run = next(iter(dt_flat.children.keys()))

    # Verify coordinates match
    c_flat = dt_flat[f"{first_run}/inlet"]["coordinates"].values
    c_trans = dt_trans[f"{first_run}/inlet"]["coordinates"].values
    c_vtu = dt_vtu[f"{first_run}/inlet"]["coordinates"].values
    assert np.allclose(c_flat, c_trans)
    assert np.allclose(c_flat, c_vtu)

    # Verify pressure field matches
    p_flat = dt_flat[f"{first_run}/inlet"]["pressure"].values
    p_trans = dt_trans[f"{first_run}/inlet"]["pressure"].values
    p_vtu = dt_vtu[f"{first_run}/inlet"]["pressure"].values
    assert np.allclose(p_flat, p_trans)
    assert np.allclose(p_flat, p_vtu)

    # Verify vector velocity field matches
    v_flat = dt_flat[f"{first_run}/inlet"]["velocity"].values
    v_trans = dt_trans[f"{first_run}/inlet"]["velocity"].values
    v_vtu = dt_vtu[f"{first_run}/inlet"]["velocity"].values
    assert v_flat.shape == (12, 2)
    assert np.allclose(v_flat, v_trans)
    assert np.allclose(v_flat, v_vtu)


def test_comsol_transient_netcdf_roundtrip(tmp_path: Path) -> None:
    """Test transient ingestion, NetCDF-4 export, and xarray.open_datatree re-import."""
    schema = {
        "title": "Transient 2D Pump Study",
        "source": "COMSOL Multiphysics 6.0",
        "attr": {
            "institution": "TU Darmstadt",
        },
        "variables": {
            "Inlet Flow": "Q_in",
            "Speed": "rot_rpm",
        },
        "time": "Time",
        "static": {
            "coordinates": ["x", "y"],
            "variables": {
                "velocity": ["u", "v"],
                "pressure": "p",
            },
        },
    }

    converter = ComsolConverter(data_schema=schema)
    nc_out = tmp_path / "comsol_trn_test.nc"

    out_file = converter.to_netcdf4(
        files={"static": "data/comsol/Pump2D_TRN_Static_every5th_Transpose_only3stepsForDemo.csv"},
        output_path=nc_out,
    )
    assert out_file.exists()

    # Read back with h5netcdf
    tree = xr.open_datatree(out_file, engine="h5netcdf")
    assert tree.attrs["title"] == "Transient 2D Pump Study"
    assert tree.attrs["source"] == "COMSOL Multiphysics 6.0"
    assert tree.attrs["institution"] == "TU Darmstadt"
    run_key = next(iter(tree.children.keys()))

    run_ds = tree[run_key].to_dataset()
    assert "time" in run_ds.coords
    assert len(run_ds.time) == 3
    assert run_ds["Inlet Flow"].values == 4.0
    assert run_ds["Speed"].values == 1000.0

    static_ds = tree[f"{run_key}/static"].to_dataset()
    assert static_ds.coordinates.shape == (869, 2)
    assert static_ds.pressure.shape == (3, 869)
    assert static_ds.velocity.shape == (3, 869, 2)
    assert list(static_ds.spatial.values) == ["x", "y"]
    assert static_ds.pressure.attrs.get("units") == "Pa"
    assert static_ds.velocity.attrs.get("units") == "m/s"


def test_comsol_converter_geometry_length_validation() -> None:
    """Test that geometry list length must match file list length."""
    import pytest

    converter = ComsolConverter(geometries=["volute", "impeller"])
    with pytest.raises(ValueError, match="Length of geometries"):
        converter.to_datatree(["data/comsol/Pump2D_MRFStudy_UltraFine_Inlet.txt"])


def test_comsol_converter_autodiscovery_defaults() -> None:
    """Test schema auto-discovery with default arguments (Option A: pure literal 1D scalars)."""
    inlet_path = "data/comsol/Pump2D_MRFStudy_UltraFine_Inlet.txt"
    converter = ComsolConverter(title="Autodiscovered Dataset")

    tree = converter.to_datatree(inlet_path)
    assert tree.attrs["title"] == "Autodiscovered Dataset"

    run_key = next(iter(tree.children.keys()))
    run_ds = tree[run_key].to_dataset()

    # In steady-state, no time dimension should be auto-created
    assert "time" not in run_ds.coords

    # Top-level parameters should be auto-extracted with exact raw header names
    assert "Q_in" in run_ds
    assert "rot_rpm" in run_ds

    # Geometry group defaults to "geometry_1"
    assert "geometry_1" in tree[run_key].children
    geom_ds = tree[f"{run_key}/geometry_1"].to_dataset()

    # When variables is empty, all fields are kept as 1D scalars with raw names
    assert "u" in geom_ds and geom_ds["u"].ndim == 1
    assert "v" in geom_ds and geom_ds["v"].ndim == 1
    assert "p" in geom_ds and geom_ds["p"].ndim == 1


def test_comsol_converter_parameters_and_variables_mini_schema() -> None:
    """Test variables mini-schema, parameter mapping, and unmentioned literal fields."""
    inlet_path = "data/comsol/Pump2D_MRFStudy_UltraFine_Inlet.txt"
    converter = ComsolConverter(
        geometries=["inlet"],
        variables={"velocity": ["u", "v"]},
        parameters={"flow": "Q_in", "rpm": "rot_rpm"},
    )
    tree = converter.to_datatree([inlet_path])

    run_key = next(iter(tree.children.keys()))
    run_ds = tree[run_key].to_dataset()

    assert "flow" in run_ds
    assert "rpm" in run_ds
    assert "inlet" in tree[run_key].children

    inlet_ds = tree[f"{run_key}/inlet"].to_dataset()
    assert "velocity" in inlet_ds
    assert inlet_ds.velocity.ndim == 2
    assert inlet_ds.velocity.dims == ("node", "spatial")
    # 'p' was not mentioned in variables, so it is kept as raw 1D scalar 'p'
    assert "p" in inlet_ds
    assert inlet_ds["p"].ndim == 1


def test_comsol_converter_custom_vector_variables() -> None:
    """Test custom vector variables in mini-schema grouping components into a 2D variable (node, spatial)."""
    blades_path = "data/comsol/Pump2D_MRFStudy_UltraFine_Blades.txt"
    converter = ComsolConverter(
        geometries=["blades"],
        variables={
            "velocity": ["u", "v"],
            "total_traction": ["spf.T_stressx", "spf.T_stressy"],
            "rotation angle": "rot1.alpha",
        },
    )
    tree = converter.to_datatree([blades_path])
    run_key = next(iter(tree.children.keys()))
    blades_ds = tree[f"{run_key}/blades"].to_dataset()

    assert "velocity" in blades_ds
    assert blades_ds["velocity"].dims == ("node", "spatial")

    assert "total_traction" in blades_ds
    assert blades_ds["total_traction"].dims == ("node", "spatial")
    assert blades_ds["total_traction"].shape[1] == 2
    assert "spf.T_stressx" not in blades_ds
    assert "spf.T_stressy" not in blades_ds
    assert "rotation angle" in blades_ds
    # Unmentioned 'p' and 'w' are preserved as 1D scalars
    assert "p" in blades_ds and blades_ds["p"].ndim == 1
    assert "w" in blades_ds and blades_ds["w"].ndim == 1


def test_comsol_converter_alias_bridge_for_variables() -> None:
    """Test custom_aliases acting as a vocabulary bridge for variables mini-schema."""
    inlet_path = "data/comsol/Pump2D_MRFStudy_UltraFine_Inlet.txt"
    converter = ComsolConverter(
        geometries=["inlet"],
        custom_aliases={"custom_u_var": "u", "custom_v_var": "v"},
        variables={"velocity": ["custom_u_var", "custom_v_var"]},
    )
    tree = converter.to_datatree([inlet_path])
    run_key = next(iter(tree.children.keys()))
    inlet_ds = tree[f"{run_key}/inlet"].to_dataset()
    assert "velocity" in inlet_ds
    assert inlet_ds["velocity"].dims == ("node", "spatial")


def test_comsol_converter_excluded_variables() -> None:
    """Test excluded_variables filters out specific raw variables without alias matching."""
    inlet_path = "data/comsol/Pump2D_MRFStudy_UltraFine_Inlet.txt"
    converter = ComsolConverter(
        geometries=["inlet"],
        excluded_variables=["w"],
    )
    tree = converter.to_datatree([inlet_path])
    run_key = next(iter(tree.children.keys()))
    inlet_ds = tree[f"{run_key}/inlet"].to_dataset()

    assert "u" in inlet_ds
    assert "v" in inlet_ds
    assert "p" in inlet_ds
    # 'w' must be strictly excluded
    assert "w" not in inlet_ds


def test_comsol_converter_schema_priority() -> None:
    """Test that explicit data_schema has strict priority over shorthand arguments."""
    schema = {
        "title": "Strict Schema Priority",
        "variables": {"manual_flow": "Q_in"},
        "custom_domain": {
            "coordinates": ["x", "y"],
            "variables": {"p_scalar": "p"},
        },
    }
    converter = ComsolConverter(
        data_schema=schema,
        geometries=["ignored_geom"],
        variables=["ignored_var"],
        parameters=["ignored_param"],
        attributes={"ignored_attr": "value"},
    )
    tree = converter.to_datatree(
        {"custom_domain": "data/comsol/Pump2D_MRFStudy_UltraFine_Inlet.txt"}
    )

    assert tree.attrs["title"] == "Strict Schema Priority"
    assert "ignored_attr" not in tree.attrs
    run_key = next(iter(tree.children.keys()))
    run_ds = tree[run_key].to_dataset()

    assert "manual_flow" in run_ds
    assert "ignored_param" not in run_ds
    assert "custom_domain" in tree[run_key].children
    assert "ignored_geom" not in tree[run_key].children


def test_comsol_converter_attributes_in_shorthand() -> None:
    """Test that attributes dictionary sets root attributes when data_schema is not set."""
    inlet_path = "data/comsol/Pump2D_MRFStudy_UltraFine_Inlet.txt"
    converter = ComsolConverter(
        attributes={"author": "Bruno", "institution": "TU Darmstadt"},
    )
    tree = converter.to_datatree(inlet_path)
    assert tree.attrs["author"] == "Bruno"
    assert tree.attrs["institution"] == "TU Darmstadt"


def test_comsol_converter_autodiscovery_roundtrip(tmp_path: Path) -> None:
    """Test NetCDF-4 export and re-import of autodiscovered dataset."""
    demo_path = "data/comsol/Pump2D_TRN_Static_every5th_Transpose_only3stepsForDemo.csv"
    converter = ComsolConverter(geometries=["static_demo"])
    out_file = tmp_path / "autodiscovered_demo.nc"

    nc_path = converter.to_netcdf4([demo_path], out_file)
    assert nc_path.exists()

    tree = xr.open_datatree(nc_path, engine="h5netcdf")
    run_key = next(iter(tree.children.keys()))
    assert "static_demo" in tree[run_key].children
