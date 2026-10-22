#
# Post-process the original MODIS-COSP files
#   The original data come in netcdf4 files with one group per primary variable.
#   These functions extract the space/time mean, per 1-degree grid cell for each month,
#   and normalize joint histograms so they are expressed as cloud fractions rather
#   than a number of observations.
#
import re
import xarray as xr
import numpy  as np


def get_from_group(f, g):
    return xr.open_dataset(f, engine="netcdf4", group=g)


def add_coords(ds, dates, template_file):
    #
    # When accessing a group the lat and lon variables are indexes, not numerical values
    #
    template = xr.open_dataset(template_file, engine="netcdf4")
    ds["latitude"]  = template.latitude
    ds["longitude"] = template.longitude
    ds = ds.rename({"date": "time"})
    ds["time"] = ("time", dates)
    ds["time"].attrs = {"standard_name": "time", "long_name": "month start"}
    return ds, template.attrs


###########################
# Scalar variables

def make_scalars(dates, files, vars):
    """Data set with monthly-mean values of scalar variables; one entry per (date, file)"""
    def mean_of(f, v):
        g = get_from_group(f, v)
        return g.Mean.T.assign_attrs(g.attrs)
    ds = xr.Dataset(data_vars =
      {v:xr.concat([mean_of(f, v) for f in files], dim="date") for v in vars})
    # Need to delete _FillValue attribute or conflicts will arise when writing
    for v in vars:
        for a in ["_FillValue", "scale_factor", "add_offset"]:
            if a in ds[v].attrs: ds[v].attrs.pop(a)
    ds, global_attrs = add_coords(ds, dates, files[0])
    # Copy global attributes
    return ds.assign_attrs(global_attrs)


###########################
# Joint histograms

def rename_dims(name):
    dimname = re.sub("_[67]",   "", name)    # Remove _6 or _7
    dimname = re.sub("jhisto_", "", dimname) # jhisto_
    #
    # Optical thickness and cloud top pressure bins are the same across joint histograms
    #
    if "optical_thickness" in dimname :
        dimname = re.sub("_total", "", dimname)
        dimname = re.sub("_liquid", "", dimname)
        dimname = re.sub("_ice", "", dimname)
    return(dimname)


def ds_name(jhisto_name):
    return("JHisto_vs_" + jhisto_name)


def group_name(host_var, jhisto):
    name = host_var
    if "PCL"    in jhisto: name = name + "_PCL"
    if "Liquid" in jhisto: name = name + "_Liquid"
    if "Ice"    in jhisto: name = name + "_Ice"
    return name


def make_jhisto(dates, files, host_var, jhisto):
    """Time series of a normalized joint histogram (expressed as cloud fractions)"""
    gname = group_name(host_var, jhisto)
    hname = f"{host_var}_vs_{jhisto}"
    def normalized(f):
        g = get_from_group(f, gname)
        return (g[ds_name(jhisto)].assign_attrs(g.attrs) /
                get_from_group(f, "Cloud_Retrieval_Fraction_Total").Pixel_Counts)
    ds = xr.Dataset(data_vars = {hname: xr.concat([normalized(f) for f in files], dim="date")})
    ds, _ = add_coords(ds, dates, files[0])
    #
    # Add histogram coordinates - central values and bounds
    #   Optical thickness or cloud water path
    #
    hist = get_from_group(files[0], gname)[ds_name(jhisto)]
    dimname    = [d for d in ds.dims if "optical_thickness" in d or "water_path" in d][0]
    boundaries = hist.JHisto_Bin_Boundaries
    ds[dimname] = boundaries[:-1] + 0.5 * np.diff(boundaries)
    ds[dimname + "_bnds"] = boundaries # Being written as a coordinate, not sure why
    #
    # Particle size or pressure dimension - the joint variables
    #
    dimname    = [d for d in ds.dims if "particle" in d or "pressure" in d][0]
    boundaries = hist.JHisto_Bin_Boundaries_Joint_Parameter
    ds[dimname] = boundaries[:-1] + 0.5 * np.diff(boundaries)
    ds[dimname + "_bnds"] = boundaries # Being written as a coordinate, not sure why
    #
    # Rename dims; put latitude, longitude last to match the scalar variables
    ds = ds.rename({d:rename_dims(d) for d in ds.dims if 'jhisto' in d})
    return(ds.transpose(..., "latitude", "longitude"))
