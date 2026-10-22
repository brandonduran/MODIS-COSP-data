#! /usr/bin/env python
#
# Download and post-process the MODIS-COSP record in chunks of N years so that only
#   N years of original data (~0.75 GB/year) are on disk at any time. For each chunk:
#     download -> post-process -> write one netCDF file per variable group per year -> delete original files
#   Years already recorded as complete in <out_dir>/manifest.json are skipped, so an interrupted
#   run can simply be started again.
#
#   python -m modis_cosp.pipeline --start 2002 --end 2025 --chunk-years 4
#
import os
import shutil
import argparse
import datetime
from   pathlib import Path
import pandas as pd

from . import config, download, outputs, process


def expected_months(year, today=None):
    """Month-start dates in ``year`` that are part of the record and have already ended"""
    today = today or datetime.date.today()
    first = max(datetime.date(year, 1, 1), config.RECORD_START)
    dates = pd.date_range(first, datetime.date(year, 12, 1), freq="MS")
    return dates[dates < pd.Timestamp(today.year, today.month, 1)]


def find_file(raw_dir, date):
    """Original file for one month, looked for in <raw_dir>/<year>/ then <raw_dir>/ (the old flat layout)"""
    day_of_year = date.timetuple().tm_yday
    pattern = f"{config.PRODUCT}.A{date.year}{day_of_year:03d}.{int(config.COLLECTION):03d}.*.nc"
    for d in [Path(raw_dir).joinpath(str(date.year)), Path(raw_dir)]:
        matches = sorted(d.glob(pattern))
        # If the month has been reprocessed keep the most recent production time stamp
        if matches: return matches[-1]
    return None


def process_year(year, raw_dir, out_dir, hpairs, today=None):
    dates = expected_months(year, today)
    found = [(d, find_file(raw_dir, d)) for d in dates]
    missing = [d.strftime("%Y-%m") for d, f in found if f is None]
    found   = [(d, f) for d, f in found if f is not None]
    if missing:
        print(f"  {year}: no original files for {', '.join(missing)}")
    if not found:
        return False
    dates = pd.DatetimeIndex([d for d, _ in found])
    files = [f for _, f in found]
    print(f"  {year}: processing {len(files)} months")

    scalars = process.make_scalars(dates, files, config.SCALAR_VARS)
    outputs.write_netcdf(scalars, outputs.scalar_path(out_dir, year), config.SCALAR_VARS)
    for host_var, jhisto in hpairs:
        hname = f"{host_var}_vs_{jhisto}"
        ds = process.make_jhisto(dates, files, host_var, jhisto)
        outputs.write_netcdf(ds, outputs.jhisto_path(out_dir, hname, year), [hname])

    complete = not missing
    outputs.record_year(out_dir, year, [d.strftime("%Y-%m") for d in dates], complete,
                        [f"{h}_vs_{j}" for h, j in hpairs])
    return complete


def chunks(years, n):
    return [years[i:i+n] for i in range(0, len(years), n)]


def run(start, end, chunk_years, raw_dir, out_dir, include_pcl=False, keep_raw=False,
        overwrite=False, skip_download=False):
    hpairs = config.jhisto_pairs(include_pcl)
    hnames = [f"{h}_vs_{j}" for h, j in hpairs]
    years  = list(range(max(start, config.RECORD_START.year), end + 1))
    todo   = [y for y in years if overwrite or not outputs.year_is_done(out_dir, y, hnames)]
    skipped = sorted(set(years) - set(todo))
    if skipped:
        print(f"Already complete, skipping: {', '.join(map(str, skipped))}")

    for chunk in chunks(todo, chunk_years):
        print(f"Chunk {chunk[0]}-{chunk[-1]}")
        for year in chunk:
            if not skip_download:
                print(f"  {year}: downloading")
                download.download_year(year, Path(raw_dir).joinpath(str(year)))
        for year in chunk:
            process_year(year, raw_dir, out_dir, hpairs)
        # Only delete what this run downloaded, never files that were already on disk
        if not (keep_raw or skip_download):
            for year in chunk:
                shutil.rmtree(Path(raw_dir).joinpath(str(year)), ignore_errors=True)

    incomplete = [y for y in years if not outputs.year_is_done(out_dir, y, hnames)]
    if incomplete:
        print(f"Incomplete years (missing months, re-run later to fill in): {', '.join(map(str, incomplete))}")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__ or "Chunked MODIS-COSP download and post-processing")
    parser.add_argument("--start", type=int, default=config.RECORD_START.year, help="first year (default: start of record)")
    parser.add_argument("--end",   type=int, default=datetime.date.today().year, help="last year (default: this year)")
    parser.add_argument("--chunk-years", type=int, default=config.DEFAULT_CHUNK_YEARS,
                        help=f"years downloaded and processed together (default: {config.DEFAULT_CHUNK_YEARS})")
    parser.add_argument("--raw-dir", default=os.environ.get("MODIS_DATA_CACHE_DIR", "modis-data-original"),
                        help="where original files are downloaded (default: $MODIS_DATA_CACHE_DIR)")
    parser.add_argument("--out-dir", default=config.DEFAULT_OUT_DIR, help="where post-processed files are written")
    parser.add_argument("--include-pcl", action="store_true",
                        help="also build joint histograms for partly cloudy (PCL) pixels")
    parser.add_argument("--keep-raw", action="store_true", help="keep original files after processing")
    parser.add_argument("--overwrite", action="store_true", help="re-process years already complete")
    parser.add_argument("--skip-download", action="store_true",
                        help="process original files already in --raw-dir; nothing is downloaded or deleted")
    args = parser.parse_args(argv)
    if args.chunk_years < 1:
        parser.error("--chunk-years must be at least 1")
    run(args.start, args.end, args.chunk_years, args.raw_dir, args.out_dir,
        include_pcl=args.include_pcl, keep_raw=args.keep_raw,
        overwrite=args.overwrite, skip_download=args.skip_download)


if __name__ == "__main__":
    main()
