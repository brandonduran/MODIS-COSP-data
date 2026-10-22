#! /usr/bin/env python
#
# Merge the per-year post-processed files into one file per variable group covering a period
#     <dest>/modis-cosp-scalars_<YYYYMM>-<YYYYMM>.nc
#     <dest>/modis-cosp-<histogram>_<YYYYMM>-<YYYYMM>.nc
#
#   python -m modis_cosp.merge --start 2003 --end 2020
#   python -m modis_cosp.merge --start 2021-07 --end 2026-08 --variables scalars Cloud_Optical_Thickness_Total_vs_Cloud_Top_Pressure
#
import argparse
from   pathlib import Path
import pandas as pd

from . import config, outputs


def available_groups(out_dir):
    """"scalars" plus the name of every joint histogram that has been post-processed"""
    jdir = Path(out_dir).joinpath("jhisto")
    return ["scalars"] + (sorted(d.name for d in jdir.iterdir() if d.is_dir()) if jdir.is_dir() else [])


def merge(out_dir, dest, start=None, end=None, groups=None, overwrite=False):
    dest = Path(dest)
    written = []
    known = available_groups(out_dir) + config.SCALAR_VARS
    for name in groups or available_groups(out_dir):
        if name not in known:
            print(f"{name}: not a processed joint histogram, 'scalars', or a scalar variable; skipping")
            continue
        try:
            ds = (outputs.open_scalars(out_dir, start, end) if name == "scalars" else
                  outputs.open_variable(name, out_dir, start, end))
        except FileNotFoundError:
            ds = None
        if ds is None or ds.time.size == 0:
            print(f"{name}: no data between {start} and {end}")
            continue
        times  = ds.indexes["time"]
        gaps   = pd.date_range(times[0], times[-1], freq="MS").difference(times)
        if len(gaps) > 0:
            print(f"{name}: note, {len(gaps)} months missing in the merged period: "
                  f"{', '.join(f'{g:%Y-%m}' for g in gaps[:6])}{' ...' if len(gaps) > 6 else ''}")
        period = f"{times[0]:%Y%m}-{times[-1]:%Y%m}"
        path = dest.joinpath(f"modis-cosp-{name}_{period}.nc")
        if path.exists() and not overwrite:
            print(f"{name}: {path} exists, skipping (use --overwrite to replace)")
            continue
        print(f"{name}: writing {ds.time.size} months to {path}")
        outputs.write_netcdf(ds, path, list(ds.data_vars))
        written.append(path)
    return written


def main(argv=None):
    parser = argparse.ArgumentParser(description="Merge per-year post-processed MODIS-COSP files over a period")
    parser.add_argument("--out-dir", default=config.DEFAULT_OUT_DIR, help="post-processed data written by the pipeline")
    parser.add_argument("--dest", help="where merged files are written (default: <out-dir>/merged)")
    parser.add_argument("--start", help="first year or month, e.g. 2003 or 2021-07 (default: first available)")
    parser.add_argument("--end",   help="last year or month, e.g. 2020 or 2026-08 (default: last available)")
    parser.add_argument("--variables", nargs="+", metavar="NAME",
                        help="'scalars', scalar variable names, and/or joint histogram names (default: 'scalars' and every processed joint histogram)")
    parser.add_argument("--overwrite", action="store_true", help="replace merged files that already exist")
    args = parser.parse_args(argv)
    merge(args.out_dir, args.dest or Path(args.out_dir).joinpath("merged"),
          args.start, args.end, args.variables, args.overwrite)


if __name__ == "__main__":
    main()
