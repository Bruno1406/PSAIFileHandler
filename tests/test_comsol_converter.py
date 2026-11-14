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
