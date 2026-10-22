#! /usr/bin/env python
#
# Download and post-process the MODIS-COSP record in chunks of N years so that only
#   N years of original data (~0.75 GB/year) are on disk at any time. For each chunk:
#     download -> post-process -> write one netCDF file per variable group per year -> delete original files
#   Months already processed (recorded in <out_dir>/manifest.json) are skipped, and months whose
#   original files are already on disk are not downloaded again, so an interrupted run can simply
#   be started again. Start and end can be years or months, so a partial year can be processed now
#   and later months added to the same yearly files as they become available.
#
#   python -m modis_cosp.pipeline --start 2002 --end 2025 --chunk-years 4
#   python -m modis_cosp.pipeline --start 2026-01 --end 2026-08
#
import os
import argparse
import datetime
from   pathlib import Path
import pandas as pd

from . import config, download, outputs, process


def parse_month(s, is_end=False):
    """First day of the month given as "YYYY" or "YYYY-MM"; a bare year means January (or December if ``is_end``)"""
    s = str(s)
    if len(s) == 4:
        return pd.Timestamp(int(s), 12 if is_end else 1, 1)
    return pd.Timestamp(s).to_period("M").to_timestamp()


def requested_months(start, end, today=None):
    """Month-start dates between ``start`` and ``end`` that are part of the record and have already ended"""
    today = today or datetime.date.today()
    first = max(pd.Timestamp(start), pd.Timestamp(config.RECORD_START))
    dates = pd.date_range(first, pd.Timestamp(end), freq="MS")
    return dates[dates < pd.Timestamp(today.year, today.month, 1)]


def record_months(year):
    """All months of ``year`` that belong to the record"""
    first = max(pd.Timestamp(year, 1, 1), pd.Timestamp(config.RECORD_START))
    return pd.date_range(first, pd.Timestamp(year, 12, 1), freq="MS")


def find_file(raw_dir, date):
    """Original file for one month, looked for in <raw_dir>/<year>/ then <raw_dir>/ (the old flat layout)"""
    day_of_year = date.timetuple().tm_yday
    pattern = f"{config.PRODUCT}.A{date.year}{day_of_year:03d}.{int(config.COLLECTION):03d}.*.nc"
    for d in [Path(raw_dir).joinpath(str(date.year)), Path(raw_dir)]:
        matches = sorted(d.glob(pattern))
        # If the month has been reprocessed keep the most recent production time stamp
        if matches: return matches[-1]
    return None


def fetch(dates, raw_dir):
    """Download the months in ``dates`` that are not already on disk; returns the files that were downloaded"""
    new = []
    for date in dates:
        if find_file(raw_dir, date) is not None:
            print(f"  {date:%Y-%m}: already downloaded")
            continue
        dest = Path(raw_dir).joinpath(str(date.year))
        before = set(dest.iterdir()) if dest.is_dir() else set()
        print(f"  {date:%Y-%m}: downloading")
        download.download_month(date, dest)
        new += sorted(set(dest.iterdir()) - before)
    return new


def process_year(year, dates, raw_dir, out_dir, hpairs):
    """Process the months ``dates`` of ``year`` and add them to that year's output files"""
    hnames  = [f"{h}_vs_{j}" for h, j in hpairs]
    found   = [(d, find_file(raw_dir, d)) for d in dates]
    missing = [d.strftime("%Y-%m") for d, f in found if f is None]
    found   = [(d, f) for d, f in found if f is not None]
    if missing:
        print(f"  {year}: no original files for {', '.join(missing)}")
    if not found:
        return
    dates = pd.DatetimeIndex([d for d, _ in found])
    files = [f for _, f in found]
    print(f"  {year}: processing {len(files)} months")
    previous = outputs.done_months(out_dir, year, hnames)

    scalars = process.make_scalars(dates, files, config.SCALAR_VARS)
    outputs.update_netcdf(scalars, outputs.scalar_path(out_dir, year), config.SCALAR_VARS)
    for host_var, jhisto in hpairs:
        hname = f"{host_var}_vs_{jhisto}"
        ds = process.make_jhisto(dates, files, host_var, jhisto)
        outputs.update_netcdf(ds, outputs.jhisto_path(out_dir, hname, year), [hname])

    months   = sorted(set(previous) | {d.strftime("%Y-%m") for d in dates})
    complete = set(months) == {d.strftime("%Y-%m") for d in record_months(year)}
    outputs.record_year(out_dir, year, months, complete, hnames)


def chunks(years, n):
    return [years[i:i+n] for i in range(0, len(years), n)]


def run(start, end, chunk_years, raw_dir, out_dir, include_pcl=False, keep_raw=False,
        overwrite=False, skip_download=False):
    hpairs = config.jhisto_pairs(include_pcl)
    hnames = [f"{h}_vs_{j}" for h, j in hpairs]
    months = requested_months(parse_month(start), parse_month(end, is_end=True))
    if len(months) == 0:
        print("No months of the record in the requested period")
        return

    todo = {}
    for year in sorted(set(months.year)):
        done = set() if overwrite else set(outputs.done_months(out_dir, year, hnames))
        wanted = [d for d in months[months.year == year] if d.strftime("%Y-%m") not in done]
        if wanted: todo[year] = wanted
    skipped = sorted(set(months.year) - set(todo))
    if skipped:
        print(f"Already processed, skipping: {', '.join(map(str, skipped))}")

    for chunk in chunks(list(todo), chunk_years):
        print(f"Chunk {chunk[0]}-{chunk[-1]}")
        downloaded = []
        if not skip_download:
            for year in chunk:
                downloaded += fetch(todo[year], raw_dir)
        for year in chunk:
            process_year(year, todo[year], raw_dir, out_dir, hpairs)
        # Only delete what this run downloaded, never files that were already on disk
        if not keep_raw:
            for f in downloaded:
                f.unlink(missing_ok=True)
            for year in chunk:
                d = Path(raw_dir).joinpath(str(year))
                if d.is_dir() and not any(d.iterdir()): d.rmdir()

    for year in sorted(set(months.year)):
        done = set(outputs.done_months(out_dir, year, hnames))
        absent = [d.strftime("%Y-%m") for d in months[months.year == year] if d.strftime("%Y-%m") not in done]
        if absent:
            print(f"Not yet processed (no data available yet, or a failed download; re-run later): {', '.join(absent)}")


def main(argv=None):
    parser = argparse.ArgumentParser(description="Chunked MODIS-COSP download and post-processing")
    parser.add_argument("--start", default=str(config.RECORD_START.year),
                        help="first year or month, e.g. 2003 or 2026-01 (default: start of record)")
    parser.add_argument("--end",   default=str(datetime.date.today().year),
                        help="last year or month, e.g. 2025 or 2026-08 (default: latest available)")
    parser.add_argument("--chunk-years", type=int, default=config.DEFAULT_CHUNK_YEARS,
                        help=f"years downloaded and processed together (default: {config.DEFAULT_CHUNK_YEARS})")
    parser.add_argument("--download-dir", "--raw-dir", dest="raw_dir",
                        default=os.environ.get("MODIS_DATA_CACHE_DIR", "modis-data-original"),
                        help="where original files are downloaded (default: $MODIS_DATA_CACHE_DIR, else ./modis-data-original)")
    parser.add_argument("--out-dir", default=config.DEFAULT_OUT_DIR, help="where post-processed files are written")
    parser.add_argument("--include-pcl", action="store_true",
                        help="also build joint histograms for partly cloudy (PCL) pixels")
    parser.add_argument("--keep-raw", action="store_true", help="keep downloaded original files after processing")
    parser.add_argument("--overwrite", action="store_true", help="re-process months already processed")
    parser.add_argument("--skip-download", action="store_true",
                        help="only process original files already in --download-dir")
    args = parser.parse_args(argv)
    if args.chunk_years < 1:
        parser.error("--chunk-years must be at least 1")
    try:
        parse_month(args.start); parse_month(args.end)
    except ValueError:
        parser.error("--start and --end must look like YYYY or YYYY-MM")
    run(args.start, args.end, args.chunk_years, args.raw_dir, args.out_dir,
        include_pcl=args.include_pcl, keep_raw=args.keep_raw,
        overwrite=args.overwrite, skip_download=args.skip_download)


if __name__ == "__main__":
    main()
