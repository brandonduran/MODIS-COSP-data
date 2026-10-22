This repository contains Python scripts for manipulating the 
[monthly data](https://ladsweb.modaps.eosdis.nasa.gov/missions-and-measurements/products/MCD06COSP_M3_MODIS) produced 
by the MODIS cloud group in support of the MODIS simulator for climate models. The data are described in  
Pincus et al, 2023: Updated observations of clouds by MODIS for global model assessment, available at 
https://crew.ldeo.columbia.edu/people/robert-pincus/

The data record available at the time of this writing extends from July 2002 to Feb 2023. 

# Downloading and post-processing data

The full record of original files is about 16 GB, so the `modis_cosp` package downloads and 
post-processes it in chunks of N years (4 by default). For each chunk it downloads the original 
monthly files, post-processes them, writes one netCDF file per variable group per year, and then 
deletes the original files, so only N years of original data (~0.75 GB/year) are on disk at once.

```
export EARTHDATA_TOKEN=...          # see below
export MODIS_DATA_CACHE_DIR=...     # scratch space for the original files
python -m modis_cosp.pipeline --start 2002 --end 2025 --chunk-years 4 --out-dir data-processed
```

Downloading the data requires an authentication token for the website in environment variable `EARTHDATA_TOKEN`. 
The simple process for obtaining a token is described on the 
[data distribution website](https://ladsweb.modaps.eosdis.nasa.gov/learn/download-files-using-laads-daac-tokens/). 
Downloads use `wget`, which retries the "Internal Server Error"s the NASA server returns a small fraction 
of the time.

Post-processing extracts the monthly mean of scalar variables and normalizes the joint histograms so they 
are expressed as cloud fractions (see the documentation paper). Joint histograms for partly cloudy (PCL) 
pixels have no counterpart in models and are skipped unless `--include-pcl` is given; the PCL scalar 
variables are always kept. Output is written as 
```
data-processed/
  scalars/modis-cosp-scalars_<year>.nc
  jhisto/<histogram>/modis-cosp-<histogram>_<year>.nc
  manifest.json
```
with a `time` coordinate holding the start of each month. `manifest.json` records which years are complete. 
Completed years are skipped when the pipeline is run again, so an interrupted run can simply be restarted; 
years with months missing (e.g. the current year, or after a failed download) are processed with the months 
available and re-done on the next run. Other options:

- `--keep-raw` keeps the original files after processing
- `--skip-download` processes original files already in `--raw-dir` (either in per-year subdirectories or one 
  flat directory as written by `download-data-with-wget.sh`); nothing is downloaded or deleted
- `--overwrite` re-processes years that are already complete

Post-processed data can be read for any variable and time frame with 
```python
from modis_cosp.outputs import open_variable, open_scalars
cf   = open_variable("Cloud_Mask_Fraction", "data-processed", "2003", "2010")
hist = open_variable("Cloud_Optical_Thickness_Total_vs_Cloud_Top_Pressure", "data-processed", "2021-07", "2021-07")
```

Python code relies on the modules listed in `environment.yml`. These may be installed with 
[conda](https://docs.conda.io/): 
```
conda env create -f environment.yml
conda activate modis-cosp-data
``` 

## Original scripts

`download-data-with-wget.sh` (download the whole record to `MODIS_DATA_CACHE_DIR`) and 
`process-local-data.py` (post-process it into single netCDF files and a Zarr store) are kept 
as they were used for the documentation paper. 

# Reproducing figures from the description paper

Figures from the data description paper can be generated from the post-processed data 
(or a subset containing July 2021, processed with `--include-pcl`) with the Jupyter notebook `MODIS-COSP-Data-Paper-Figures.md`. 
The notebook is saved in the compact [Jupytext](https://jupytext.readthedocs.io) format, which 
is installed via `environment.yml`. Starting the Jupyter notebook and setting variables 
`figDir` and `dataDir` should reproduce the figures. 

[![DOI](https://zenodo.org/badge/523775968.svg)](https://zenodo.org/badge/latestdoi/523775968)