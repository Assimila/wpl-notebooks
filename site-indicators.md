# Site-level peat health indicator

The WorldPeatland project defines the concept of a site-level peat health indicator,
which is spatially representative over an entire peatland site, or sub-region of interest.

## Inputs

1. Peat extent map (geometry or raster pixel mask), classifying the spatial extent of peat to monitor across the site.
2. Spatio-temporal datasets (e.g. land surface temperature, leaf area index, water level, etc.).
3. Variable loadings from expert knowledge or singular value decomposition.

## Processing

1. Using the peat extent map as a mask, extract time series from each spatio-temporal dataset.
   These time series "zonal statistics" provide representative measurements *with variance*.
2. Resample / interpolate and align all time series onto
   a common **daily** time step,
   and a common **annual** time step (one data point per year).
3. For each dataset, calculate daily and annual climatologies.
4. Compute dimensionless z-scores (standard anomalies) for each variable,
   relative to its daily and annual climatology.
5. Combine the z-scores according to the variable loadings to produce
   daily and annual peat health indicators.

### Water level

There is a small caveat for the water level variable.
This stems from the implicit assumption that variables are monotonically correlated to peat health.
However, the water level can be both too high and too low.
Therefore we define a "water level delta" as the absolute deviation from some expert-defined optimal water level $w^*$,
and use this in the peat health indicator.

```math
\delta_t = | x_t - w^* |
```

### Climatology and z-scores

#### Daily climatology

Firstly compute the *inverse-variance weighted* mean $\mu_{\mathrm{ord}}$
and standard deviation $\sigma_{\mathrm{ord}}$
across the multi-year timeseries,
according to ordinal day-of-year.

For an observation $x_t$ the z-score is defined by:

```math
z_t = \frac{x_t - \mu_{\mathrm{ord}(t)}}{ \sigma_{\mathrm{ord}(t)} }
```

This results in a z-score, or standard anomaly, that indicates how many standard deviations the observation is
from the climatological mean.

##### Leap years

To handle leap years, we drop 29 February from the time series,
and compute 365 daily climatologies.

When calculating the z-scores, we apply the 28 February climatology to 29 February.

#### Annual climatology

Firstly compute the *inverse-variance weighted* mean $\mu_{\mathrm{ann}}$
and standard deviation $\sigma_{\mathrm{ann}}$
across the multi-year timeseries.

For an observation $x_t$ the z-score is defined by:

```math
z_t = \frac{x_t - \mu_{\mathrm{ann}}}{ \sigma_{\mathrm{ann}} }
```

This results in a z-score, or standard anomaly, that indicates how many standard deviations the observation is
from the climatological mean.

### Variable loadings

Given loadings $l_v \in [-1, +1]$ for each variable $v$ we compute normalised weights $w_v$

```math
w_v = \frac{l_v}{ \sum_{v'} | l_{v'} | }
```

and then combine the z-scores for all variables $z_{v, t}$ into the peat health indicator $\mathrm{PHI}_t$

```math
\mathrm{PHI}_t = \sum_v w_v z_{v, t}
```

## Dashboard functionality

For the WorldPeatland dashboard, we want to present various "flavours" of the peat health indicator, based on 

1. different values of optimal water level $w^*$. 
2. different variable loadings.
3. daily vs annual data.

We also want to allow users to tweak these parameters according the their own preference,
and to see the effect of these changes on the peat health indicator in real-time.

This requires that we pre-compute the time series for each spatio-temporal dataset (based on a peat extent map),
and package this data into a format that can be loaded by the dashboard on the fly.

## Serialisation format

This is a directory structure that contains the following

```bash
$ tree .
.
├── info.json
├── peat_extent.tiff
├── time_series.h5
└── variable_loading
    ├── expert.json
    ├── svd.json
    └── ...
```

### info.json

This file contains metadata about the peat health indicator dataset.

```json
{
    "name": <string>,
    "description": <string>,
    "site_id": <string>,
    "default_variable_loading_name": <string>,
    "units": {
        <variable name>: <string>
    }
}
```

`name` and `description` are for display purposes in the dashboard.

`site_id` is a unique identifier for the peatland site,
which should map to a STAC sub-catalog id.

The combination of `site_id` and `name` should be unique.

`default_variable_loading_name` should correspond to the `name` attribute of one of the files in the `variable_loading` directory.

`units` is a required key that specifies optional units for each variable.

### Peat map (peat_extent.tiff)

A GeoTIFF file containing a single band.
This is a pixel mask of peat extent,
where pixels with a value of 1 indicate peat and 0 indicate non-peat.

- Should have an integer dtype such as BYTE (8-bit unsigned integer).
- Should have EPSG:4326 (WGS84) coordinate reference system.

### Time series data

Pre-computed time series data for each spatio-temporal dataset.
Should contain both daily and annual time series data covering multiple years - sufficient to compute climatologies.
Serialised to HDF5 using pandas [to_hdf](https://pandas.pydata.org/docs/reference/api/pandas.DataFrame.to_hdf.html).

The HDF group "data" should contain a pandas DataFrame with a daily time series index.

- Each column corresponds to a variable.
- Values are daily observations in whatever unit is most appropriate, not z-scores.

The HDF group "variance" should contain a pandas DataFrame with a daily time series index.

- Index as per the "data" group.
- Columns as per the "data" group.
- Values equate to the variance of the corresponding daily observation.

The HDF group "annual_data" should contain a pandas DataFrame with an annual time series index.

- Columns as per the "data" group.
- Values are annual means with the same unit as the "data" group, not z-scores.

The HDF group "annual_variance" should contain a pandas DataFrame with an annual time series index.

- Index as per the "annual_data" group.
- Columns as per the "data" group.
- Values equate to the variance of the corresponding annual mean.

### Variable loadings

We need to be able to specify multiple variable loadings,
hence this `variable_loading/` directory contains potentially many JSON files.

Each json file has structure:

```json
{
    "name": <string>,
    "description": <string>,
    "optimal_values": {
        <variable name>: <float>
    },
    "variable_loadings": {
        <variable name>: <float>
    }
}
```

`name` should be unique.

The default variable loading should have `name` corresponding to `default_variable_loading_name` in `info.json`, 

The presence of a key in `optimal_values` indicates that the variable should be transformed to the absolute deviation from the specified value.
