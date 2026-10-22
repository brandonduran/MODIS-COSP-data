#! /usr/bin/env python
#
# Compare a model's MODIS-simulator output with the post-processed MODIS-COSP observations
#   Produces two figures:
#     - maps of the model and observed time means and their difference (model - obs), with the
#       model regridded to the 1x1 degree MODIS grid
#     - global, Northern and Southern Hemisphere mean time series of the observations over the
#       whole record, with the period used for the comparison shaded (unless it is the full record)
#
#   python -m modis_cosp.compare CLTMODIS --model "/path/to/case.cam.h2.*.nc"
#   python -m modis_cosp.compare CLWMODIS --model case.cam.h2.*.nc --start 2010 --end 2014
#   python -m modis_cosp.compare --help     # lists the variables available for comparison
#
#   New variables are added to VARIABLES; each entry says how to find the model and observed
#   fields. Only scalar (lat-lon) fields are implemented so far.
#
import argparse
import glob
from   dataclasses import dataclass
from   pathlib import Path
import numpy  as np
import pandas as pd
import xarray as xr

from . import config, outputs

# Default comparison period: the full years of the record
DEFAULT_START = "2003"
DEFAULT_END   = "2025"


@dataclass
class Variable:
    model:     str          # name in the model history files
    obs:       str          # name in the post-processed MODIS-COSP files
    long_name: str
    units:     str          # units both fields are converted to
    kind:      str = "scalar"
    vmin:      float = 0.
    vmax:      float = 100.
    cmap:      str = "viridis"
    diff_max:  float = 30.  # color scale limit for model - obs


#
# Cloud fractions from the MODIS simulator are compared to the retrieval fractions,
#   i.e. the fraction of pixels in which a cloud was detected and its properties retrieved,
#   which is what the simulator mimics (Pincus et al. 2023)
#
VARIABLES = {
    "CLTMODIS": Variable("CLTMODIS", "Cloud_Retrieval_Fraction_Total",  "Total cloud fraction",  "%"),
    "CLWMODIS": Variable("CLWMODIS", "Cloud_Retrieval_Fraction_Liquid", "Liquid cloud fraction", "%"),
    "CLIMODIS": Variable("CLIMODIS", "Cloud_Retrieval_Fraction_Ice",    "Ice cloud fraction",    "%"),
}


###########################
# Units

def to_percent(da):
    """Express a fraction as percent, using the units attribute or, failing that, the data range"""
    units = str(da.attrs.get("units", "")).strip().lower()
    if units in ("%", "percent"):
        return da
    if units not in ("1", "fraction", "none", "unitless") and float(da.max()) > 1.5:
        return da
    return (100 * da).assign_attrs(da.attrs, units="%")


def convert(da, units):
    if units == "%":
        return to_percent(da).assign_attrs(units="%")
    return da


###########################
# Reading

def expand_paths(patterns):
    """Model files from paths and/or glob patterns (patterns can be quoted to avoid long command lines)"""
    files = []
    for p in patterns:
        matches = sorted(glob.glob(str(Path(p).expanduser())))
        files += matches if matches else [p]
    missing = [f for f in files if not Path(f).exists()]
    if missing:
        raise FileNotFoundError(f"Model files not found: {', '.join(missing)}")
    return files


def _time_from_bounds(ds):
    """CAM stamps monthly means at the end of the month; use the middle of the averaging interval"""
    bname = ds["time"].attrs.get("bounds")
    for b in [bname, "time_bnds", "time_bnd"]:
        if b and b in ds:
            bnds = ds[b].values
            mid  = [lo + (hi - lo) / 2 for lo, hi in bnds]
            return ds.assign_coords(time=("time", mid, ds["time"].attrs))
    return ds


def _open_cftime(f):
    """Open with times decoded as cftime objects, as model calendars are often not Gregorian"""
    if hasattr(xr, "coders") and hasattr(xr.coders, "CFDatetimeCoder"):
        return xr.open_dataset(f, decode_times=xr.coders.CFDatetimeCoder(use_cftime=True))
    return xr.open_dataset(f, use_cftime=True)


def open_model(files, name, start=None, end=None):
    """One model variable from a set of history files, optionally limited to ``start``-``end``"""
    def load(f):
        ds = _open_cftime(f)
        if name not in ds:
            raise KeyError(f"{name} is not in {f}")
        ds = _time_from_bounds(ds)
        keep = [name] + [c for c in ["lat", "lon"] if c in ds and "ncol" in ds[c].dims]
        return ds[keep].load()
    ds = xr.concat([load(f) for f in files], dim="time", data_vars="minimal",
                   coords="minimal", compat="override").sortby("time")
    ds = ds.sel(time=slice(start, end))
    if ds.time.size == 0:
        raise ValueError(f"No model data for {name} between {start} and {end}")
    da = ds[name]
    if "ncol" in da.dims:
        da = da.assign_coords(lat=ds["lat"], lon=ds["lon"])
    return da


def open_obs(name, obs_dir, start=None, end=None):
    """One observed variable, with latitude and longitude ascending"""
    da = outputs.open_variable(name, obs_dir, start, end)[name]
    return da.sortby("latitude").sortby("longitude")


###########################
# Regridding to the observational grid

def _edges(centers, lo=None, hi=None):
    c   = np.asarray(centers, dtype=float)
    mid = 0.5 * (c[1:] + c[:-1])
    e   = np.concatenate([[c[0] - (mid[0] - c[0])], mid, [c[-1] + (c[-1] - mid[-1])]])
    if lo is not None: e = np.maximum(e, lo)
    if hi is not None: e = np.minimum(e, hi)
    return e


def _overlap(src, dst):
    """Length of the overlap between each destination (rows) and source (columns) interval"""
    lo = np.maximum(dst[:-1, None], src[None, :-1])
    hi = np.minimum(dst[1:,  None], src[None,  1:])
    return np.clip(hi - lo, 0, None)


def regrid_conservative(da, lat, lon, min_coverage=0.5):
    """Area-conservative regridding of a field on a regular lat-lon grid (dims "lat", "lon") to
    the grid with cell centers ``lat``, ``lon``. Destination cells less than ``min_coverage``
    covered by valid source data are missing.
    """
    da = da.sortby("lat").sortby("lon")
    # Latitude overlaps are measured in sin(latitude) so they are proportional to area
    wlat = _overlap(np.sin(np.deg2rad(_edges(da.lat, -90, 90))),
                    np.sin(np.deg2rad(_edges(lat, -90, 90))))
    src_lon = _edges(da.lon)
    dst_lon = _edges(lon)
    wlon = sum(_overlap(src_lon + shift, dst_lon) for shift in (-360., 0., 360.))

    data  = da.transpose(..., "lat", "lon").values
    valid = np.isfinite(data)
    num = np.einsum("ij,...jk,lk->...il", wlat, np.where(valid, data, 0.), wlon)
    den = np.einsum("ij,...jk,lk->...il", wlat, valid.astype(float),     wlon)
    full = wlat.sum(axis=1)[:, None] * wlon.sum(axis=1)[None, :]
    with np.errstate(invalid="ignore", divide="ignore"):
        out = np.where(den >= min_coverage * full, num / den, np.nan)

    dims   = [d for d in da.dims if d not in ("lat", "lon")] + ["latitude", "longitude"]
    coords = {d: da[d] for d in dims[:-2] if d in da.coords}
    coords.update(latitude=np.asarray(lat), longitude=np.asarray(lon))
    return xr.DataArray(out, dims=dims, coords=coords, attrs=da.attrs)


def regrid_unstructured(da, lat, lon):
    """Regrid a field on an unstructured grid (dim "ncol", with "lat" and "lon" coordinates) to the
    regular grid with cell centers ``lat``, ``lon`` by averaging the columns in each cell. Cells
    containing no column take the value of the nearest column.
    """
    from scipy.spatial import cKDTree

    lat_e, lon_e = _edges(lat, -90, 90), _edges(lon)
    clat = da["lat"].values
    clon = (da["lon"].values - lon_e[0]) % 360. + lon_e[0]
    i = np.clip(np.searchsorted(lat_e, clat, side="right") - 1, 0, len(lat) - 1)
    j = np.clip(np.searchsorted(lon_e, clon, side="right") - 1, 0, len(lon) - 1)
    cell  = i * len(lon) + j
    ncell = len(lat) * len(lon)

    def xyz(la, lo):
        la, lo = np.deg2rad(la), np.deg2rad(lo)
        return np.stack([np.cos(la) * np.cos(lo), np.cos(la) * np.sin(lo), np.sin(la)], axis=-1)
    has_cols = np.bincount(cell, minlength=ncell) > 0
    glat, glon = np.meshgrid(lat, lon, indexing="ij")
    empty = np.flatnonzero(~has_cols)
    _, nearest = cKDTree(xyz(clat, da["lon"].values)).query(xyz(glat.ravel()[empty], glon.ravel()[empty]))

    data = da.transpose(..., "ncol").values
    flat = data.reshape(-1, data.shape[-1])
    out  = np.full((flat.shape[0], ncell), np.nan)
    for n, row in enumerate(flat):
        valid = np.isfinite(row)
        tot = np.bincount(cell[valid], weights=row[valid], minlength=ncell)
        cnt = np.bincount(cell[valid], minlength=ncell)
        with np.errstate(invalid="ignore", divide="ignore"):
            out[n] = np.where(cnt > 0, tot / cnt, np.nan)
        out[n, empty] = row[nearest]

    dims   = [d for d in da.dims if d != "ncol"] + ["latitude", "longitude"]
    coords = {d: da[d] for d in dims[:-2] if d in da.coords}
    coords.update(latitude=np.asarray(lat), longitude=np.asarray(lon))
    return xr.DataArray(out.reshape(data.shape[:-1] + (len(lat), len(lon))),
                        dims=dims, coords=coords, attrs=da.attrs)


def regrid_to_obs(da, obs):
    """Regrid a model field to the (1x1 degree) grid of the observed field ``obs``"""
    if "ncol" in da.dims:
        return regrid_unstructured(da, obs.latitude.values, obs.longitude.values)
    if "lat" in da.dims and "lon" in da.dims:
        return regrid_conservative(da, obs.latitude.values, obs.longitude.values)
    raise ValueError(f"Don't know how to regrid a field with dimensions {da.dims}")


###########################
# Statistics

def area_mean(da, lat_min=-90, lat_max=90):
    """Area-weighted mean over valid points between ``lat_min`` and ``lat_max``"""
    da = da.sel(latitude=slice(lat_min, lat_max))
    return da.weighted(np.cos(np.deg2rad(da.latitude))).mean(("latitude", "longitude"))


def area_rmse(da):
    return float(np.sqrt(area_mean(da ** 2)))


###########################
# Figures

def period_label(times):
    return f"{times[0].strftime('%Y-%m')} to {times[-1].strftime('%Y-%m')}"


def plot_maps(model, obs, var, title, path):
    import matplotlib.pyplot as plt
    import cartopy.crs as ccrs

    # Statistics use the points where both fields are available
    both  = np.isfinite(model) & np.isfinite(obs)
    diff  = model - obs
    proj  = ccrs.Robinson(central_longitude=180)
    fig, axes = plt.subplots(1, 3, figsize=(17, 5), subplot_kw={"projection": proj},
                             layout="constrained")
    panels = [(model, "Model",       dict(cmap=var.cmap, vmin=var.vmin, vmax=var.vmax)),
              (obs,   "MODIS",       dict(cmap=var.cmap, vmin=var.vmin, vmax=var.vmax)),
              (diff,  "Model - MODIS", dict(cmap="RdBu_r", vmin=-var.diff_max, vmax=var.diff_max))]
    for ax, (field, name, style) in zip(axes, panels):
        mesh = ax.pcolormesh(field.longitude, field.latitude, field, transform=ccrs.PlateCarree(),
                             shading="auto", rasterized=True, **style)
        ax.coastlines(linewidth=0.5)
        ax.set_global()
        mean = float(area_mean(field.where(both)))
        stats = f"mean {mean:.1f} {var.units}"
        if field is diff:
            stats = f"bias {mean:.1f}, RMSE {area_rmse(diff.where(both)):.1f} {var.units}"
        ax.set_title(f"{name}\n{stats}", fontsize=11)
        if field is not obs:
            fig.colorbar(mesh, ax=axes[:2] if field is model else ax, orientation="horizontal",
                         shrink=0.6, pad=0.04, label=f"{var.long_name} ({var.units})")
    fig.suptitle(title)
    fig.savefig(path, dpi=150)
    plt.close(fig)


def plot_timeseries(obs, var, title, path, period=None, model_means=None):
    """Global, NH and SH mean time series of ``obs``; ``period`` (start, end) is shaded if given and
    ``model_means`` (one value per panel) are drawn as horizontal lines"""
    import matplotlib.pyplot as plt

    regions = [("Global", -90, 90), ("Northern Hemisphere", 0, 90), ("Southern Hemisphere", -90, 0)]
    fig, axes = plt.subplots(3, 1, figsize=(10, 8), sharex=True, layout="constrained")
    for n, (ax, (name, lo, hi)) in enumerate(zip(axes, regions)):
        series = area_mean(obs, lo, hi)
        ax.plot(series.time, series, color="0.5", linewidth=0.8, label="MODIS monthly")
        ax.plot(series.time, series.rolling(time=12, center=True).mean(),
                color="k", linewidth=1.8, label="MODIS 12-month running mean")
        if model_means is not None:
            ax.axhline(model_means[n], color="tab:red", linestyle="--", linewidth=1.2,
                       label="Model time mean")
        if period is not None:
            ax.axvspan(period[0], period[1], color="0.85", zorder=0, label="Comparison period")
        ax.set_title(name, fontsize=11)
        ax.set_ylabel(f"{var.units}")
    axes[0].legend(fontsize=8, ncols=2, loc="best")
    fig.suptitle(title)
    fig.savefig(path, dpi=150)
    plt.close(fig)


###########################
# Comparison

def case_name(files):
    name = Path(files[0]).name
    return name.split(".cam.")[0] if ".cam." in name else Path(name).stem


def compare(name, model_files, obs_dir=config.DEFAULT_OUT_DIR, start=DEFAULT_START, end=DEFAULT_END,
            model_start=None, model_end=None, fig_dir="figures", case=None, model_var=None, fmt="png"):
    var = VARIABLES[name]
    if var.kind != "scalar":
        raise NotImplementedError(f"Comparisons of {var.kind} variables are not implemented yet")
    case = case or case_name(model_files)

    obs_all = convert(open_obs(var.obs, obs_dir), var.units)
    obs     = obs_all.sel(time=slice(start, end))
    if obs.time.size == 0:
        raise ValueError(f"No MODIS data between {start} and {end} in {obs_dir}")
    model = convert(open_model(model_files, model_var or var.model, model_start, model_end), var.units)

    obs_mean   = obs.mean("time")
    model_mean = regrid_to_obs(model.mean("time"), obs_mean)

    obs_times   = obs.indexes["time"]
    model_times = model.indexes["time"]
    tag = f"{case}_{name}_{obs_times[0]:%Y%m}-{obs_times[-1]:%Y%m}"
    fig_dir = Path(fig_dir)
    fig_dir.mkdir(parents=True, exist_ok=True)

    title = (f"{var.long_name}: {case} ({period_label(model_times)}) vs "
             f"MODIS {var.obs} ({period_label(obs_times)})")
    maps = fig_dir.joinpath(f"{tag}_maps.{fmt}")
    plot_maps(model_mean, obs_mean, var, title, maps)

    # Shade the comparison period unless it is the full record
    full   = obs_all.sel(time=slice(DEFAULT_START, DEFAULT_END)).indexes["time"]
    period = None if (obs_times[0] == full[0] and obs_times[-1] == full[-1]) else \
             (obs_times[0], obs_times[-1] + pd.offsets.MonthEnd(1))
    # Model means are taken where the observations are available, as in the maps
    masked = model_mean.where(np.isfinite(obs_mean))
    model_means = [float(area_mean(masked, lo, hi)) for lo, hi in [(-90, 90), (0, 90), (-90, 0)]]
    series = fig_dir.joinpath(f"{tag}_timeseries.{fmt}")
    plot_timeseries(obs_all, var, f"MODIS {var.long_name} ({var.obs}); model: {case}",
                    series, period, model_means)
    return maps, series


def variables_help():
    width = max(len(k) for k in VARIABLES)
    lines = ["variables available for comparison (model name: MODIS-COSP counterpart):"]
    lines += [f"  {k:<{width}}  {v.long_name} ({v.units}): {v.obs}" for k, v in VARIABLES.items()]
    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Compare model MODIS-simulator output with MODIS-COSP observations: "
                    "maps of model, MODIS, and model - MODIS (model regridded to the 1x1 degree "
                    "MODIS grid) and global/NH/SH time series of the MODIS record.",
        epilog=variables_help(), formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("variable", choices=VARIABLES, metavar="variable",
                        help="variable to compare (see list below)")
    parser.add_argument("--model", nargs="+", required=True,
                        help="model history files; glob patterns are expanded (quote them to avoid long command lines)")
    parser.add_argument("--obs-dir", default=config.DEFAULT_OUT_DIR,
                        help="directory of post-processed MODIS-COSP data (default: %(default)s)")
    parser.add_argument("--start", default=DEFAULT_START,
                        help="first year or month (YYYY or YYYY-MM) of MODIS data to compare (default: %(default)s)")
    parser.add_argument("--end", default=DEFAULT_END,
                        help="last year or month of MODIS data to compare (default: %(default)s)")
    parser.add_argument("--model-start", help="first year or month of model data to use (default: all)")
    parser.add_argument("--model-end",   help="last year or month of model data to use (default: all)")
    parser.add_argument("--model-var", help="name of the variable in the model files, if not the default")
    parser.add_argument("--case", help="label for the model in titles and file names (default: from the file names)")
    parser.add_argument("--fig-dir", default="figures", help="directory for figures (default: %(default)s)")
    parser.add_argument("--format", default="png", help="figure file format (default: %(default)s)")
    args = parser.parse_args(argv)

    figs = compare(args.variable, expand_paths(args.model), args.obs_dir, args.start, args.end,
                   args.model_start, args.model_end, args.fig_dir, args.case, args.model_var, args.format)
    for f in figs:
        print(f"Wrote {f}")


if __name__ == "__main__":
    main()
