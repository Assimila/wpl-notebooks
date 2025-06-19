# Site-level peat health indicator

The WorldPeatland project defines the concept of a site-level peat health indicator,
which is spatially representative over an entire peatland site.

## Inputs

1. Peat extent map (geometry), classifying the spatial extent of peat to monitor across the site.
2. Spatio-temporal datasets (e.g. land surface temperature, leaf area index, water level, etc.).
3. Variable loadings from expert knowledge or singular value decomposition.

## Processing

1. Using the peat extent map as a mask, extract time series from each spatio-temporal dataset.
   These time series "zonal statistics" provide representative measurements *with variance*.
2. Resample / linearly interpolate and align all time series onto a common daily time step.
3. For each dataset, calculate daily climatologies.
4. Compute dimensionless z-scores (standard anomalies) for each variable, relative to its climatology.
5. Combine the z-scores according to the variable loadings to produce the final peat health indicator.

### Water level

There is a small caveat for the water level variable.
This stems from the implicit assumption that variables are linearly correlated to peat health.
However, the water level can be both too high and too low.
Therefore we define a "water level delta" as the absolute deviation from some expert-defined optimal water level $w^*$,
and use this in the peat health indicator.

```math
\delta_t = | x_t - w^* |
```

### Climatology and z-scores

Firstly compute the *inverse-variance weighted* mean $\mu_{\mathrm{ord}}$
and standard deviations $\sigma_{\mathrm{ord}}$
across the multi-year timeseries,
according to ordinal day-of-year.

For an observation $x_t$ the z-score is defined by:

```math
z_t = \frac{x_t - \mu_{\mathrm{ord}(t)}}{ \sigma_{\mathrm{ord}(t)} }
```

This results in a z-score, or standard anomaly, that indicates how many standard deviations the observation is
from the climatological mean.

#### Leap years

To handle leap years, we drop 29 February from the time series,
and compute 365 daily climatologies.

When calculating the z-scores, we apply the 28 February climatology to 29 February.

### Variable loadings

Given loadings $l_v$ for each variable $v$ we compute normalised weights $w_v$

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
├── peat_extent.geojson
├── time_series.h5
└── variable_loading
    ├── expert.json
    ├── svd.json
    └── ...
```

### info.json

This file contains metadata about the peat health indicator dataset.
Name and description are for display purposes in the dashboard.
The `default_variable_loading` maps to a file in the `variable_loading` directory.

```json
{
    "name": <string>,
    "description": <string>,
    "default_variable_loading": "expert.json"
}
```

### Peat map (geometry)

A GeoJSON file containing a single MultiPolygon geometry.
The geometry may be quite complex.
Note that GeoJSON is [implicitly](https://datatracker.ietf.org/doc/html/rfc7946#section-4) in WGS84 (EPSG:4326) coordinate reference system.

### Time series data

Pre-computed time series data for each spatio-temporal dataset.
Serialised to HDF5 using pandas [to_hdf](https://pandas.pydata.org/docs/reference/api/pandas.DataFrame.to_hdf.html).

The HDF group "data" should contain a pandas DataFrame with a daily time series index. 
Each column corresponds to a variable.
Values are observations in whatever unit is most appropriate, not z-scores.

The HDF group "variance" should contain a pandas DataFrame with an identical time series index and columns to the "data" group.
Values equate to the variance of the corresponding observation.

### Variable loadings

We need to be able to specify multiple variable loadings.
The default variable loading is specified in `info.json` under the key `default_variable_loading`.

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

The presence of a key in `optimal_values` indicates that the variable should be transformed to the absolute deviation from the specified value.
