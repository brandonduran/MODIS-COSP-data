#
# Download monthly files from the LAADS archive
#   Based on the wget script shown at https://ladsweb.modaps.eosdis.nasa.gov/archive/allData/62/MCD06COSP_M3_MODIS/
#   The server requires a token (https://ladsweb.modaps.eosdis.nasa.gov/learn/download-files-using-laads-daac-tokens/)
#   read from the environment variable EARTHDATA_TOKEN
#
import os
import re
import subprocess
from   pathlib import Path

from . import config


def _wget(url, dest, token=None, tries=5):
    token = token or os.environ.get("EARTHDATA_TOKEN")
    if not token:
        raise RuntimeError("Downloading requires an Earthdata token in EARTHDATA_TOKEN")
    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=True)
    cmd = ["wget", "-e", "robots=off", "-m", "-nv", "-np", "-nd",
           "-R", ".html,.tmp,.csv,.json",
           f"--tries={tries}", "--waitretry=10", "--retry-on-http-error=500,502,503,504",
           "--header", f"Authorization: Bearer {token}",
           "-P", str(dest), url]
    result = subprocess.run(cmd)
    # The server's intermittent errors mean wget can exit non-zero even when most files arrived;
    #   missing months are detected and reported when the data are processed
    if result.returncode != 0:
        print(f"  wget exited with status {result.returncode} for {url}; continuing")
    # Clean up leftover directory listings (named by day of year)
    for f in dest.iterdir():
        if re.fullmatch(r"[0-9]{3}", f.name): f.unlink()


def download_year(year, dest, token=None, tries=5):
    """Mirror all monthly files for ``year`` into the flat directory ``dest``.

    Files already present are skipped by wget, so a failed download can simply be re-run.
    """
    _wget(f"{config.ARCHIVE_URL}/{year}/", dest, token, tries)


def download_month(date, dest, token=None, tries=5):
    """Download the monthly file starting on ``date`` into the flat directory ``dest``.

    The archive has one directory per month, named by the day of year of the month's first day.
    """
    day_of_year = date.timetuple().tm_yday
    _wget(f"{config.ARCHIVE_URL}/{date.year}/{day_of_year:03d}/", dest, token, tries)
