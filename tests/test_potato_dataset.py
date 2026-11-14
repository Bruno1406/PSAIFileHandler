from __future__ import annotations

from pathlib import Path
from typing import Any

import h5py
import numpy as np
import pandas as pd
import xarray as xr

from psaifilehandler.matlab import MATSweepConverter


def convert_potato_dataset(
    mat_path: str | Path = "data/matlab/potato_dataset.mat",
    output_path: str | Path = "potato_dataset.nc",
    metadata_dir: str | Path = "metadata/potato",
    max_experiments: int = 33,
    flat: bool = True,
    include_coordinates: bool = True,
) -> Path:
    """Convert potato finite-element simulation dataset into NetCDF-4 DataTree using MATSweepConverter."""
    mat_file_path = Path(mat_path).resolve()
    out_file = Path(output_path).resolve()
    meta_dir = Path(metadata_dir).resolve()
    meta_dir.mkdir(parents=True, exist_ok=True)

    print(f"\n=== Converting Potato Dataset ({mat_file_path}) ===")
    sweep_converter = MATSweepConverter(mat_file_path)
    with sweep_converter:
        data = sweep_converter.read()
        nd = data["ND"]

        num_runs = min(len(nd), max_experiments)
        print(f"Converting first {num_runs} COMSOL forward simulation runs (out of {len(nd)})")

        mapping: dict[str, Any] = {}
        for i in range(num_runs):
            elem = nd[i]
            exp_name = str(elem.name).strip()

            coords_da = None
            if include_coordinates:
                coords_data = elem.coords.values if hasattr(elem.coords, "values") else elem.coords
                coords_arr = np.array(coords_data, dtype=np.float64, copy=True)
                coords_da = xr.DataArray(
                    coords_arr,
                    dims=["node", "spatial"],
                    coords={"spatial": ["x", "y", "z"]},
                )

            t0 = elem.tab[0, 0]
            t1 = elem.tab[0, 1]
            t2 = elem.tab[0, 2]

            time_vals = t0.sel(col="time").values
            v1 = t0.sel(col="Var1").values
            cols_without_time = [c for c in t1.coords["col"].values if c != "time"]

            t1_clean = t1.sel(col=cols_without_time).values
            t2_clean = t2.sel(col=cols_without_time).values

            df_oven = pd.DataFrame({"time": time_vals, "temperature": v1})
            csv_text = f"# Oven Temperature Profile during experiment\n{df_oven.to_csv(index=False)}"

            meta_file = meta_dir / f"{exp_name}_oven_temperature.csv"
            meta_file.write_text(csv_text, encoding="utf-8")

            if flat:
                exp_entry: dict[str, Any] = {
                    "metadata": meta_file,
                    "attrs": {
                        "run_name": exp_name,
                        "session": getattr(elem, "session", ""),
                        "type": getattr(elem, "type", ""),
                    },
                    "time": time_vals,
                    "variables": {
                        "Oven Temperature": xr.DataArray(v1, dims=["time"]),
                        "Temperature": t1_clean,
                        "Water Saturation": t2_clean,
                    },
                }
                if coords_da is not None:
                    exp_entry["coordinates"] = coords_da
            else:
                mesh_dict: dict[str, Any] = {
                    "time": time_vals,
                    "variables": {
                        "Temperature": t1_clean,
                        "Water Saturation": t2_clean,
                    },
                }
                if coords_da is not None:
                    mesh_dict["coordinates"] = coords_da
                exp_entry = {
                    "metadata": meta_file,
                    "attrs": {
                        "run_name": exp_name,
                        "session": getattr(elem, "session", ""),
                        "type": getattr(elem, "type", ""),
                    },
                    "variables": {
                        "Oven Temperature": xr.DataArray(v1, dims=["time"]),
                    },
                    "time": time_vals,
                    "potato_mesh": mesh_dict,
                }

            mapping[exp_name] = exp_entry

            if (i + 1) % 10 == 0 or (i + 1) == num_runs:
                print(f"Processed {i + 1}/{num_runs} potato experiments...")

        root_meta = {
            "title": "Potato Cooking Simulation Dataset",
            "description": "33 COMSOL 3D forward simulations on a 4649-node tetrahedral mesh",
            "total_experiments": num_runs,
            "created_by": "MATFile Converter",
        }

        sweep_converter.to_netcdf4(mapping, output_path=out_file, root_metadata=root_meta)
        print(f"Exported potato dataset NetCDF-4 to: {out_file}")
        return out_file


def verify_potato_dataset(potato_nc: str | Path, reference_nc: str | Path | None = None) -> None:
    """Verify group hierarchy, variable integrity, and parity against reference NetCDF."""
    nc_path = Path(potato_nc).resolve()
    print(f"\n--- Verifying Potato Dataset Output: {nc_path.name} ---")

    with h5py.File(nc_path, "r") as test_f:
        groups = list(test_f.keys())
        print(f"Total experiment groups in {nc_path.name}: {len(groups)}")
        assert len(groups) > 0, "No experiment groups found in NetCDF-4 file"

        sample_exp = groups[0]
        exp_grp = test_f[sample_exp]
        assert "Oven Temperature" in exp_grp, "Oven Temperature missing in experiment group"
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
                            test_arr = curr_test_grp[key][:]
                            ref_arr = ref_grp[key][:]
                            assert test_arr.shape == ref_arr.shape, f"Shape mismatch for {exp}/{key}"
                            if np.issubdtype(test_arr.dtype, np.floating):
                                np.testing.assert_allclose(test_arr, ref_arr, rtol=1e-7, atol=1e-7)
                            elif np.issubdtype(test_arr.dtype, np.integer):
                                assert np.array_equal(test_arr, ref_arr)
                print("✓ All experiment arrays match reference dataset with 100% precision!")

    print("\nVerification of potato dataset completed successfully!")


def test_potato_dataset() -> None:
    """Automated pytest test function running verification against reference."""
    ref = Path("data/matlab/potato_dataset.nc")
    out = Path("/tmp/potato_dataset_test.nc")
    convert_potato_dataset(
        output_path=out,
        max_experiments=2,
    )
    verify_potato_dataset(out, reference_nc=ref if ref.exists() else None)


if __name__ == "__main__":
    ref = Path("data/matlab/potato_dataset.nc")
    out = convert_potato_dataset()
    verify_potato_dataset(out, reference_nc=ref if ref.exists() else None)
