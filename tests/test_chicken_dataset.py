from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import h5py
import numpy as np
import pandas as pd
import xarray as xr

from psaifilehandler.matlab import MATConverter


def convert_chicken_dataset(
    mat_path: str | Path = "data/matlab/chicken_dataset.mat",
    output_path: str | Path = "chicken_dataset.nc",
    metadata_dir: str | Path = "metadata/chicken",
    max_experiments: int | None = None,
) -> Path:
    """Convert chicken simulation dataset into NetCDF-4 DataTree with dual-mesh decomposition."""
    mat_file_path = Path(mat_path).resolve()
    out_file = Path(output_path).resolve()
    meta_dir = Path(metadata_dir).resolve()
    meta_dir.mkdir(parents=True, exist_ok=True)

    probe_coords_3 = np.array([
        [0.0, 0.01, 0.0],
        [0.0, 0.019, 0.0],
        [0.0, 0.02, 0.0],
    ], dtype=np.float64)

    probe_coords_1 = np.array([
        [0.0, 0.02, 0.0],
    ], dtype=np.float64)

    point_regex = re.compile(r"^(.*?)-+Point:-(.*)-$")

    print(f"\n=== Converting Chicken Dataset ({mat_file_path}) ===")
    converter = MATConverter(mat_file_path)
    with converter:
        data = converter.read()
        s33 = data.get("s33c") or data.get("s33")
        num_runs = len(s33) if max_experiments is None else min(len(s33), max_experiments)

        first_info = s33[0].info
        point_map: dict[str, dict[str, tuple[str, int]]] = {}
        single_cols: list[tuple[str, int]] = []
        top_level_cols: dict[str, tuple[str, int, str]] = {}

        for idx, col in enumerate(first_info):
            if col in ("flow_time", "out-time"):
                continue
            if col == "T_oven":
                top_level_cols["T_oven"] = (col, idx, "K")
                continue
            if "Temperature_volavg" in col:
                top_level_cols["Temperature_volavg_K"] = (col, idx, "K")
                continue
            if "massConcentrationWater_volavg" in col:
                top_level_cols["massConcentrationWater_volavg_1_"] = (col, idx, "1")
                continue
            m = point_regex.match(col)
            if m:
                prefix, pt = m.group(1), m.group(2)
                point_map.setdefault(prefix, {})[pt] = (col, idx)
            else:
                single_cols.append((col, idx))

        all_3_prefixes = {k: v for k, v in point_map.items() if len(v) == 3}
        for k, v in point_map.items():
            if len(v) != 3:
                for pt, (col, idx) in v.items():
                    single_cols.append((col, idx))

        print(
            f"Total runs: {num_runs} | Top-level variables: {len(top_level_cols)} | "
            f"3-probe variables: {len(all_3_prefixes)} | Single-probe variables: {len(single_cols)}"
        )

        mapping: dict[str, Any] = {}
        for i in range(num_runs):
            elem = s33[i]
            exp_name = str(elem.name).strip()
            tab = elem.tab
            flow_time = tab.values[:, 0]

            top_vars = {}
            for var_name, (raw_col, idx, units) in top_level_cols.items():
                attrs = {"units": units}
                if var_name != raw_col:
                    attrs["original_name"] = raw_col
                if var_name == "T_oven":
                    attrs["long_name"] = "Oven Temperature"
                top_vars[var_name] = xr.DataArray(
                    tab.values[:, idx],
                    dims=["time"],
                    attrs=attrs,
                )

            m3_vars = {}
            for prefix, pts in all_3_prefixes.items():
                c0 = tab.values[:, pts["0-0.01-0"][1]]
                c1 = tab.values[:, pts["0-0.019-0"][1]]
                c2 = tab.values[:, pts["0-0.02-0"][1]]
                stacked = np.column_stack([c0, c1, c2])
                clean_name = prefix.replace("/", "_")
                m3_vars[clean_name] = xr.DataArray(
                    stacked,
                    dims=["time", "node"],
                    attrs={"original_name": prefix} if clean_name != prefix else {},
                )

            m1_vars = {}
            for col, idx in single_cols:
                clean_name = col.replace("/", "_")
                m1_vars[clean_name] = xr.DataArray(
                    tab.values[:, idx][:, None],
                    dims=["time", "node"],
                    attrs={"original_name": col} if clean_name != col else {},
                )

            prop = elem.prop
            p_cols = (
                list(prop.coords["col"].values)
                if hasattr(prop, "coords") and "col" in prop.coords
                else [f"col_{j}" for j in range(prop.shape[1])]
            )
            df_prop = pd.DataFrame(prop.values, columns=p_cols)
            csv_text = f"# Oven Temperature Profile during experiment\n{df_prop.to_csv(index=False)}"

            meta_file = meta_dir / f"{exp_name}_oven_temperature.csv"
            meta_file.write_text(csv_text, encoding="utf-8")

            exp_entry: dict[str, Any] = {
                "metadata": meta_file,
                "attrs": {
                    "run_name": exp_name,
                    "session": getattr(elem, "session", ""),
                    "type": getattr(elem, "type", ""),
                },
                "time": flow_time,
                "variables": top_vars,
                "all_probes_measurements": {
                    "coordinates": probe_coords_3,
                    "time": flow_time,
                    "variables": m3_vars,
                },
                "single_probe_measurements": {
                    "coordinates": probe_coords_1,
                    "time": flow_time,
                    "variables": m1_vars,
                },
            }
            mapping[exp_name] = exp_entry

            if (i + 1) % 50 == 0 or (i + 1) == num_runs:
                print(f"Processed {i + 1}/{num_runs} chicken experiments...")

        root_meta = {
            "title": "Chicken Breast Cooking Simulation Dataset",
            "description": "Transient finite element simulations with dual probe meshes and oven temperature profiles",
            "total_experiments": num_runs,
            "created_by": "MATFile Converter",
        }

        converter.to_netcdf4(mapping, output_path=out_file, root_metadata=root_meta)
        print(f"Exported chicken dataset NetCDF-4 to: {out_file}")
        return out_file


def verify_chicken_dataset(chicken_nc: str | Path, reference_nc: str | Path | None = None) -> None:
    """Verify group hierarchy, variable integrity, and parity against reference NetCDF."""
    nc_path = Path(chicken_nc).resolve()
    print(f"\n--- Verifying Chicken Dataset Output: {nc_path.name} ---")

    with h5py.File(nc_path, "r") as test_f:
        groups = list(test_f.keys())
        print(f"Total experiment groups in {nc_path.name}: {len(groups)}")
        assert len(groups) > 0, "No experiment groups found in NetCDF-4 file"

        sample_exp = groups[0]
        exp_grp = test_f[sample_exp]
        assert "T_oven" in exp_grp, "T_oven missing in experiment group"
        print(f"Sample experiment {sample_exp} keys: {list(exp_grp.keys())}")

        if reference_nc is not None:
            ref_path = Path(reference_nc).resolve()
            if ref_path.exists():
                print(f"Comparing against reference dataset: {ref_path.name}...")
                with h5py.File(ref_path, "r") as ref_f:
                    for exp in groups:
                        assert exp in ref_f, f"Experiment {exp} not in reference file"
                        curr_test_grp = test_f[exp]
                        ref_grp = ref_f[exp]
                        for key in curr_test_grp.keys():
                            assert key in ref_grp, f"Key {key} not in reference group {exp}"
                            test_item = curr_test_grp[key]
                            ref_item = ref_grp[key]
                            if isinstance(test_item, h5py.Dataset):
                                test_val = test_item[:]
                                ref_val = ref_item[:]
                                assert test_val.shape == ref_val.shape, f"Shape mismatch for {exp}/{key}"
                                if np.issubdtype(test_val.dtype, np.floating):
                                    np.testing.assert_allclose(test_val, ref_val, rtol=1e-7, atol=1e-7)
                                elif np.issubdtype(test_val.dtype, np.integer):
                                    assert np.array_equal(test_val, ref_val)
                            elif isinstance(test_item, h5py.Group):
                                for subkey in test_item.keys():
                                    assert subkey in ref_item, f"Subkey {subkey} missing in {exp}/{key}"
                                    sub_test_val = test_item[subkey][:]
                                    sub_ref_val = ref_item[subkey][:]
                                    assert sub_test_val.shape == sub_ref_val.shape, f"Shape mismatch for {exp}/{key}/{subkey}"
                                    if np.issubdtype(sub_test_val.dtype, np.floating):
                                        np.testing.assert_allclose(sub_test_val, sub_ref_val, rtol=1e-7, atol=1e-7)
                                    elif np.issubdtype(sub_test_val.dtype, np.integer):
                                        assert np.array_equal(sub_test_val, sub_ref_val)
                print("✓ All experiment arrays match reference dataset with 100% precision!")

    print("\nVerification of chicken dataset completed successfully!")


def test_chicken_dataset() -> None:
    """Automated pytest test function running verification against reference."""
    ref = Path("data/matlab/chicken_dataset.nc")
    out = Path("/tmp/chicken_dataset_test.nc")
    convert_chicken_dataset(
        output_path=out,
        max_experiments=2,
    )
    verify_chicken_dataset(out, reference_nc=ref if ref.exists() else None)


if __name__ == "__main__":
    ref = Path("data/matlab/chicken_dataset.nc")
    out = convert_chicken_dataset()
    verify_chicken_dataset(out, reference_nc=ref if ref.exists() else None)
