
import os
import pathlib
import sys
import pystac
import rioxarray
import rasterio
import xarray as xr
import dask.array as da
from glob import glob
# from osgeo import gdal
# import geopandas as gpd
# from shapely.geometry import mapping
import pandas as pd
import numpy as np

# Set matplotlib backend
import matplotlib
matplotlib.use('Agg')  # Use non-interactive backend for headless environments
import matplotlib.pyplot as plt

CATALOG_URL = "https://s3.waw3-2.cloudferro.com/swift/v1/wpl-stac/stac/catalog.json"

def read_stac_data(site, variable):
    """
    Reads ...
    """
    root: pystac.Catalog = pystac.read_file(CATALOG_URL) 

    # Get the sub-catalog for the site
    catalog: pystac.Catalog = root.get_child(site)

    # Get the collection for the corresponding variable
    collection: pystac.Collection = catalog.get_child(variable)

    # This dataset is chunked for spatial reads
    asset = collection.assets[f"{variable}.xy.zarr"]
    
    ds = xr.open_dataset(
        asset.href,
        **asset.ext.xarray.open_kwargs,  # type: ignore
    )

    return ds

def read_data_and_uncertainty(data_path, uncertainty_path):
    """
    Reads WorldPeatland data and associated uncertainty GeoTIFFs as xarray.DataArray.
    """
    lai = rioxarray.open_rasterio(data_path)
    uncertainty = rioxarray.open_rasterio(uncertainty_path)

    # Read per-band metadata for time
    d = gdal.Open(data_path)
 
    bands = d.RasterCount
    band_times = []

    for i in range(1, bands + 1):
        tags = d.GetRasterBand(i).GetMetadata()
        # Try several possible keys for date
        date_str = tags.get("RANGEBEGINNINGDATE") or tags.get("DATE") or tags.get("time") or None
        if date_str is not None:
            # Accept both YYYY-MM-DD and YYYY-MM-DDTHH:MM:SS formats
            date_str = date_str.split("T")[0]
            band_times.append(np.datetime64(date_str))
        else:
            band_times.append(np.datetime64('NaT'))

    # Rename dimensions and assign coordinates
    lai = lai.rename({"band": "time", "y": "latitude", "x": "longitude"})
    uncertainty = uncertainty.rename({"band": "time", "y": "latitude", "x": "longitude"})
    lai = lai.assign_coords(time=("time", band_times))
    uncertainty = uncertainty.assign_coords(time=("time", band_times))

    return lai, uncertainty

def get_pixel_indices_within_classification(classification_path, master, resample=True):
    """
    Returns the indices (y, x) of pixels where the classification
    is labeled as peatland, value is 1.
    """
    # Read the classification raster
    classification = rioxarray.open_rasterio(classification_path)

    # Resample (if needed), use 'nearest' for categorical data
    if resample == True:
        classification = classification.rio.reproject_match(master,
                resampling=rasterio.enums.Resampling.nearest)

    # Find indices where classification is not nan (i.e., inside the classification)
    indices = np.argwhere(classification.isel(band=0).data==1)

    # return indices
    return classification

def get_pixel_indices_within_geometry(dataarray, shapefile_path):
    """
    Returns the indices (band, y, x) of pixels in dataarray that overlap with 
    the geometry in shapefile_path.
    """
    # Read the shapefile
    gdf = gpd.read_file(shapefile_path)
    # Reproject geometry to match raster CRS
    gdf = gdf.to_crs(dataarray.rio.crs)

    # Rasterize the geometry to the shape of the dataarray
    mask = dataarray.rio.clip(gdf.geometry.apply(mapping), gdf.crs,
            all_touched=True, drop=False, invert=False)

    # Find indices where mask is not nan (i.e., inside the geometry)
    indices = np.argwhere(~np.isnan(mask.values))

    return indices

def get_weighted_mean_and_uncertainties(data, variable_metadata, indices):
    """
    Calculate weighted mean and variance for the data at the specified indices using uncertainty as weights.
    Weights are computed as the inverse of the square of uncertainty values.
    Also computes an uncertainty ratio based on weight distribution.
    Returns a DataFrame with the weighted mean, and uncertainty for each time step.
    """ 
    if len(indices) == 0:
        return None, None

    uncertainty_name = variable_metadata[1]
    variable_name = variable_metadata[2]
    spatial_ratio = variable_metadata[3]

    weighted_means = []
    uncertainties = []

    # for i in range(data[variable_name].shape[0]):
    for i in range(100):

        print(f"Processing time step {i+1}/{data[variable_name].shape[0]}...")
        # TODO
        # This should not be neecesary but might be an issue with the reprojection
        indices = indices.assign_coords({'x': data[variable_name].x.values})
        indices = indices.assign_coords({'y': data[variable_name].y.values})

        # Select pixels where classification is 1
        data_vals = data[variable_name][i].where(indices[0] == 1)

        # TODO: find a better solution for this
        if variable_name == 'water_level':
            unc_vals = data[uncertainty_name].where(indices[0] == 1)
            unc_vals *= 1.96

        elif variable_name == 'displacement':
            # TODO: Resampling to daily data should be done when STACking the
            # data rather than here
            # TODO: Set the uncertainties from INGV info and compute the zonal
            # stats without unique values...
            unc_vals = xr.where(~np.isnan(data_vals), 2.0, np.nan)

        elif 'cross_ratio' in variable_name:
            # For Sentinel-1 CPR, ≈30% (3-σ) relative uncertainty for the
            # VH/VV cross-pol ratio is a reasonable assumption
            unc_vals = xr.where(~np.isnan(data_vals), data_vals*0.3, np.nan)
        else:
            unc_vals = data[uncertainty_name][i].where(indices[0] == 1)

        # Compute weights
        weights = 1.0 / (unc_vals ** 2)

        # Avoid division by zero or nan
        valid = np.isfinite(data_vals) & np.isfinite(weights) & (weights > 0)
        data_vals = data_vals.where(valid == True)
        weights = weights.where(valid == True)

        # Calculate uncertainty
        unique_weights, counts = da.unique(weights.data, return_counts=True)
        unique_weights, counts = unique_weights.compute(), counts.compute()

        # Remove the NaN count
        not_nan_indices = ~np.isnan(unique_weights)
        unique_weights = unique_weights[not_nan_indices]
        counts = counts[not_nan_indices]

        if unique_weights.size == 1:
            weighted_mean = np.sum(data_vals * weights) / np.sum(weights)
            weighted_mean = weighted_mean.compute().item()

            uncertainty = (np.sqrt(1.0/unique_weights)) / \
                           np.sqrt(counts[0] * spatial_ratio)
            uncertainty = uncertainty.item()
        else:
            # Calculate weighted mean
            weighted_mean = np.sum(data_vals * weights) / np.sum(weights)

            # Calculate uncertainty
            #    Get the number of native pixels
            n_native_pixels = counts / spatial_ratio ** 2
            #    Get the fully covered native pixels contribution
            m = n_native_pixels.astype(int) * spatial_ratio ** 2
            # m = n_native_pixels.astype(int)
            #    Get contribution from partially covered native pixels
            c = n_native_pixels % 1 * spatial_ratio ** 2

            numerator = np.sum(((m ** 2) + (c ** 2)) * unique_weights)
            ## numerator = np.sum(((m * spatial_ratio ** 4) + (c ** 2)) * unique_weights)
            denominator = np.sum(weights) ** 2

            uncertainty = numerator / denominator if denominator != 0 else np.nan

            weighted_mean = weighted_mean.compute().item()

            if isinstance(uncertainty, xr.DataArray):
                uncertainty = uncertainty.compute().item()

        print(f"Weighted mean: {weighted_mean}, Uncertainty: {uncertainty}")

        weighted_means.append(weighted_mean)
        uncertainties.append(uncertainty)

    # Create a DataFrame to stores the weighted means and uncertainties
    df = pd.DataFrame({"weighted_mean": weighted_means,
                       "variance": uncertainties},
                       index=data['time'].values[0:100])
    
    return df

def create_plot(weighted_mean, weighted_variance, variable, site_name, aoi):
    """
    Create a plot of the zonal stats time series
    """
    # Create figure
    fig, ax = plt.subplots(figsize=(10, 5))

    # Plot weighted mean time series
    ax.plot(weighted_mean.index,
            weighted_mean,
            label=f"{variable} - weighted mean", color="C0")

    # Compute standard deviation from variance
    std = np.sqrt(weighted_variance.values)

    # Fill between mean ± std
    ax.fill_between(
        weighted_mean.index,
        weighted_mean - std,
        weighted_mean + std,
        color="C0",
        alpha=0.3,
       label=f"{variable} - weighted std dev"
    )

    ax.set_xlabel("Time")
    ax.set_ylabel(variable)
    ax.set_title(f"{variable}")
    ax.legend()
    fig.autofmt_xdate()
    plt.grid()
    plt.tight_layout()

    plt.savefig(f"/tmp/{variable}_weighted_mean_and_uncert_{site_name}_{aoi}.png",
                dpi=150)

def extract_zonal_stats(variable_metadata, site,
                        classification_fname, aoi, plot=False):
    """
    Extract zonal stats using associated uncertainties
        The stats then will be linearly interpolated to create
        synthetic daily data
    """
    # Read data and associated uncertainty
    asset_name = variable_metadata[0]
    data = read_stac_data(variable=asset_name, site=site)

    # Get the indices where the classification is 1
    indices = get_pixel_indices_within_classification(classification_fname,
                                                      master=data)

    # Compute stats
    weighted_stats = get_weighted_mean_and_uncertainties(data=data,
                         variable_metadata=variable_metadata,
                         indices=indices)

    # Linear interpolation to create synthetic daily dates, normalized first
    # to avoid having hours:minutes in the time dimension
    weighted_stats.index = weighted_stats.index.normalize() 

    # TODO compute annual weighted mean and error propagation. 
    annual_mean = weighted_stats['weighted_mean'].resample('YE').mean()
    annual_mean = annual_mean.resample('D').interpolate('linear')

    annual_uncertainty = weighted_stats['variance'].resample('YE').mean()
    annual_uncertainty = annual_uncertainty.resample('D').interpolate('linear')

    weighted_mean = weighted_stats['weighted_mean'].resample('D').interpolate('linear')
    uncertainty = weighted_stats['variance'].resample('D').interpolate('linear')

    if plot == True:
        create_plot(weighted_mean, uncertainty, asset_name, site, aoi)

    return weighted_mean, uncertainty, annual_mean, annual_uncertainty


if __name__ == "__main__":

    if len(sys.argv) != 4:

        # Check inputs
        print((f"Usage: python .zonal_stats_with_uncert.py"
               f"<site_root_data_dir> <peatland_extent_path> <ascending|descending>"))
    else:
        # Site name e.g. degero
        site = sys.argv[1]
        # ascending or descending or empty
        cross_ratio = sys.argv[3]

        # Full path of the peatland classification GeoTiff
        # e.g. /wp_data/sites/Degero/WhatSARPeat/WhatSARPeat2024_Degero.tif
        classification_fname = sys.argv[2]

        # Asset name, uncertainty name, variable name, spatial ratio
        # Spatial ratio is nominal spatial res of the product /  20
        # since 20m is the spatial res of the stored products
        variables = [['lai', 'lai_std_dev', 'lai', 25],
                     ['fpar', 'fpar_std_dev', 'fpar', 25],
                     ['albedo', 'albedo_std_dev', 'albedo', 25],
                     ['evi', 'evi_std_dev', 'evi', 50],
                     ['lst-day', 'lst_day_std_dev', 'lst_day', 50],
                     ['lst-night', 'lst_night_std_dev', 'lst_night', 50],
                     ['lst-diurnal-range', 'lst_diurnal_range_std_dev', 'lst_diurnal_range', 50],
                     ['surface-displacement', 'surface_displacement_dev', 'displacement', 0.75],
                     ['water-level', 'confidence_interval', 'water_level', 5]]

        if len(cross_ratio) > 0:
            cr = [f'cross-ratio-{cross_ratio}',
                  f'cross-ratio-{cross_ratio}_std_dev',
                  f'cross_ratio_{cross_ratio}', 1.0 ]
            variables.append(cr)

        daily_data = pd.DataFrame()
        daily_uncertainty = pd.DataFrame()

        annual_data = pd.DataFrame()
        annual_uncertainty = pd.DataFrame()

        # Get name of the AOI based on the raster filename
        aoi = pathlib.Path(os.path.basename(classification_fname)).stem

        for variable_metadata in variables:
            print(f"Processing {variable_metadata[0]}...")
            w_mu, w_unc, a_mu, a_unc = extract_zonal_stats(variable_metadata,
                    site, classification_fname, aoi, plot=True)

            variable_name = variable_metadata[2]

            if daily_data.columns.shape[0] == 0:
                daily_data[variable_name] = w_mu
                daily_uncertainty[variable_name] = w_unc

                annual_data[variable_name] = a_mu
                annual_uncertainty[variable_name] = a_unc

            else:
                # Get the union of all dates
                all_dates = daily_data.index.union(w_mu.index)

                # Reindex to the full date range
                daily_data = daily_data.reindex(all_dates)
                w_mu = w_mu.reindex(all_dates)

                daily_uncertainty = daily_uncertainty.reindex(all_dates)
                w_unc = w_unc.reindex(all_dates)

                annual_data = annual_data.reindex(all_dates)
                a_mu = a_mu.reindex(all_dates)

                annual_uncertainty = annual_uncertainty.reindex(all_dates)
                a_unc = a_unc.reindex(all_dates)

                daily_data[variable_name] = w_mu
                daily_uncertainty[variable_name] = w_unc

                annual_data[variable_name] = a_mu
                annual_uncertainty[variable_name] = a_unc

        filename = f"time_series_{site}_{aoi}.h5"
        daily_data.to_hdf(filename, key="data")
        annual_data.to_hdf(filename, key="annual_data")

        daily_uncertainty.to_hdf(filename, key="variance")
        annual_uncertainty.to_hdf(filename, key="annual_variance")

