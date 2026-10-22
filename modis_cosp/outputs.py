#
# Output naming, writing, and reading of the post-processed data
#   Each variable group is written as one netCDF file per year:
#     <out_dir>/scalars/modis-cosp-scalars_<year>.nc
#     <out_dir>/jhisto/<hname>/modis-cosp-<hname>_<year>.nc
#   and <out_dir>/manifest.json records which years are complete
#
import os
import json
import datetime
from   pathlib import Path
import xarray as xr

MANIFEST = "manifest.json"


def scalar_path(out_dir, year):
    return Path(out_dir).joinpath("scalars", f"modis-cosp-scalars_{year}.nc")


def jhisto_path(out_dir, hname, year):
    return Path(out_dir).joinpath("jhisto", hname, f"modis-cosp-{hname}_{year}.nc")


def output_paths(out_dir, year, hnames):
    return [scalar_path(out_dir, year)] + [jhisto_path(out_dir, h, year) for h in hnames]


def write_netcdf(ds, path, vars):
    """Write via a temporary file so an interrupted run never leaves a partial file in place"""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".nc.tmp")
    ds.to_netcdf(tmp, encoding={v:{"zlib": True} for v in vars})
    os.replace(tmp, path)


def update_netcdf(ds, path, vars):
    """Add the months in ``ds`` to the file at ``path``, replacing any months already there"""
    path = Path(path)
    if path.exists():
        with xr.open_dataset(path, engine="netcdf4") as old:
            old = old.load()
        old = old.sel(time=~old.time.isin(ds.time.values))
        if old.time.size > 0:
            ds = xr.concat([old, ds], dim="time", data_vars="minimal", coords="minimal",
                           compat="override", join="override").sortby("time")
    write_netcdf(ds, path, vars)


###########################
# Manifest - which years are done

def read_manifest(out_dir):
    f = Path(out_dir).joinpath(MANIFEST)
    return json.loads(f.read_text()) if f.exists() else {"years": {}}


def record_year(out_dir, year, months, complete, hnames):
    manifest = read_manifest(out_dir)
    manifest["years"][str(year)] = {
        "months":   months,
        "complete": complete,
        "jhistos":  hnames,
        "written":  datetime.datetime.now().isoformat(timespec="seconds"),
    }
    f = Path(out_dir).joinpath(MANIFEST)
    tmp = f.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(manifest, indent=2, sort_keys=True))
    os.replace(tmp, f)


def done_months(out_dir, year, hnames):
    """Months (as "YYYY-MM") of ``year`` already processed, counting only if every output file exists"""
    entry = read_manifest(out_dir)["years"].get(str(year))
    if entry is None or not all(p.exists() for p in output_paths(out_dir, year, hnames)):
        return []
    return entry["months"]


###########################
# Reading

def _year_of(f):
    return int(f.stem.rsplit("_", 1)[1])


def _open_years(files, start, end, keep=None):
    if start is not None or end is not None:
        lo = int(str(start)[:4]) if start is not None else 0
        hi = int(str(end)[:4])   if end   is not None else 9999
        files = [f for f in files if lo <= _year_of(f) <= hi]
    if not files:
        raise FileNotFoundError("No post-processed files for the requested variable and time frame")
    def load(f):
        ds = xr.open_dataset(f, engine="netcdf4")
        return ds[keep] if keep else ds
    ds = xr.concat([load(f) for f in files], dim="time", data_vars="minimal", coords="minimal",
                   compat="override", join="override")
    return ds.sel(time=slice(start, end))


def open_scalars(out_dir, start=None, end=None):
    """Open all scalar variables over a time frame (``start``, ``end`` as e.g. "2003" or "2010-06")"""
    files = sorted(Path(out_dir).joinpath("scalars").glob("modis-cosp-scalars_*.nc"))
    return _open_years(files, start, end)


def open_variable(name, out_dir, start=None, end=None):
    """Open one post-processed variable over a time frame

    :param name: a scalar variable (e.g. ``Cloud_Mask_Fraction``) or joint histogram
        (e.g. ``Cloud_Optical_Thickness_Total_vs_Cloud_Top_Pressure``)
    :param start, end: anything ``pandas`` understands as a date, e.g. "2003" or "2010-06"
    """
    jdir = Path(out_dir).joinpath("jhisto", name)
    if jdir.is_dir():
        return _open_years(sorted(jdir.glob(f"modis-cosp-{name}_*.nc")), start, end)
    return _open_years(sorted(Path(out_dir).joinpath("scalars").glob("modis-cosp-scalars_*.nc")),
                       start, end, keep=[name])
