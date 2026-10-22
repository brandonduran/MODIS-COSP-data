#
# Settings shared by the download, processing, and reading code
#
import datetime

PRODUCT      = "MCD06COSP_M3_MODIS"
COLLECTION   = "62"
ARCHIVE_URL  = f"https://ladsweb.modaps.eosdis.nasa.gov/archive/allData/{COLLECTION}/{PRODUCT}"

# First month of the data record
RECORD_START = datetime.date(2002, 7, 1)

DEFAULT_CHUNK_YEARS = 4
DEFAULT_OUT_DIR     = "data-processed"

#
# See Table 1 of Pincus et al. 2023
#
SCALAR_VARS = [
    'Solar_Zenith',
    'Solar_Azimuth',
    'Sensor_Zenith',
    'Sensor_Azimuth',
    'Cloud_Top_Pressure',
    'Cloud_Mask_Fraction',
    'Cloud_Mask_Fraction_Low',
    'Cloud_Mask_Fraction_Mid',
    'Cloud_Mask_Fraction_High',
    'Cloud_Optical_Thickness_Liquid',
    'Cloud_Optical_Thickness_Ice',
    'Cloud_Optical_Thickness_Total',
    'Cloud_Optical_Thickness_PCL_Liquid',
    'Cloud_Optical_Thickness_PCL_Ice',
    'Cloud_Optical_Thickness_PCL_Total',
    'Cloud_Optical_Thickness_Log10_Liquid',
    'Cloud_Optical_Thickness_Log10_Ice',
    'Cloud_Optical_Thickness_Log10_Total',
    'Cloud_Particle_Size_Liquid',
    'Cloud_Particle_Size_Ice',
    'Cloud_Particle_Size_PCL_Liquid',
    'Cloud_Particle_Size_PCL_Ice',
    'Cloud_Water_Path_Liquid',
    'Cloud_Water_Path_Ice',
    'Cloud_Water_Path_PCL_Liquid',
    'Cloud_Water_Path_PCL_Ice',
    'Cloud_Retrieval_Fraction_Liquid',
    'Cloud_Retrieval_Fraction_Ice',
    'Cloud_Retrieval_Fraction_Total',
    'Cloud_Retrieval_Fraction_PCL_Liquid',
    'Cloud_Retrieval_Fraction_PCL_Ice',
    'Cloud_Retrieval_Fraction_PCL_Total',
]


def jhisto_pairs(include_pcl=False):
    """(host variable, joint variable) pairs for each joint histogram - see Table 2

    Partly cloudy (PCL) pixels have no counterpart in models so are excluded by default
    """
    pcls = ["", "PCL_"] if include_pcl else [""]
    pairs = [("Cloud_Optical_Thickness_" + pcl + phase, "Cloud_Top_Pressure")
             for pcl in pcls for phase in ["Total", "Liquid", "Ice"]]
    pairs += [(host_var, f"Cloud_Particle_Size_{pcl}{phase}")
              for host_var in ["Cloud_Optical_Thickness", "Cloud_Water_Path"]
              for pcl in pcls for phase in ["Liquid", "Ice"]]
    return pairs


def jhisto_names(include_pcl=False):
    return [f"{host_var}_vs_{jhisto}" for host_var, jhisto in jhisto_pairs(include_pcl)]
