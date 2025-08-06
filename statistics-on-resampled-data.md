# Resampled statistics

For the site-level peat health indicators, we calculate raster statistics on resampled data.

For example, given:

- a (raster) map of peat location (a pixel mask)
- a data layer of some variable of interest
- an additional layer which describes the uncertainty of the data

The data layer may have been reprojected and/or resampled from its native coordinate reference system and resolution, in order to harmonise all data into a format ready for analysis.

For a single time step, we want to

1. mask the data layer with the peat location mask
2. calculate an inverse-variance weighted mean
3. propagate the uncertainty information through to a final uncertainty on the weighted mean

## Inverse-variance weighted mean

Pixel weights are defined as

```math
w_i = \frac{1}{\sigma_i^2}
```

Where $\sigma_i$ is the uncertainty of the data value $x_i$ at pixel $i$.
The weighted mean has the form

```math
\bar{x}_w = \frac{\sum_i w_i x_i}{\sum_i w_i}
```

In the case of independent data the uncertainty on the weighted mean is given by

```math
\sigma_{w}^2 = \frac{1}{\sum_i w_i}
```

However, for spatially resampled data, this assumption of independence does not hold.

## Correlated data

When data are spatially resampled from the native resolution to a higher resolution, we refer to the original pixels as "native pixels" and the new, higher resolution pixels as "sub-pixels".
These sub-pixels are not independent of each other, and so the uncertainty on the weighted mean must be adjusted to account for this correlation.

The full expression for the uncertainty on the weighted mean in the presence of correlated data is given by

```math
\sigma_{w}^2 = \sum_i \sum_j a_i a_j \rho_{ij} \sigma_i \sigma_j
```

where the coefficients $a_i$ are the normalised weights

```math
a_i = \frac{w_i}{\sum_i w_i}
```

and $\rho_{ij}$ is the correlation coefficient between sub-pixels $i$ and $j$.

## Example

As a toy example, consider the case where the pixel mask covers 3 sub-pixels, where sub-pixels 1 and 2 are correlated, and sub-pixel 3 is independent of the first two.

Here $w_1 = w_2$, $\sigma_1 = \sigma_2$, and the correlation coefficients are given by

```math
\rho = \begin{pmatrix}
1 & 1 & 0 \\
1 & 1 & 0 \\
0 & 0 & 1
\end{pmatrix}
```

therefore 

```math
\sigma_{w}^2 = \frac{ 2^2 w_1 + 1^2 w_3 }{ ( \sum_i w_i )^2 }
```

## Unique pixels

The problem is understanding which of the sampled sub-pixels belong to the same pixel in the native resolution of the data layer.

An upper bound can be achieved by counting the number of observations $n_w$ of each unique weight $w$, and assuming that all observations of the same weight are correlated - as if sampling $n_w$ observations from the same native pixel.

```math
\sigma_{w}^2 \leq \frac{ \sum_w n_w^2 w }{ ( \sum_i w_i )^2 }
```

where $\sum_w$ is the sum over unique weights $w$.

An improved upper bound can be achieved if we know the resampling ratio $r$,
which is the ratio of sub-pixels per native resolution pixel.

## Example 2

Consider the case of a 2x2 resampling $r=4$,
where the pixel mask covers 5 sub-pixels, 
and where the weights $w$ of all sub-pixels are equal. 
In this case, we could assume that all 5 sub-pixels belong to the same native pixel (as above).
But since we know the resampling ratio $r$, we can improve the upper bound by 
noting that a maximum of $r=4$ sub-pixels can be correlated. 

```math
\sigma_{w}^2 \leq \frac{ (4^2 + 1^2) w }{ ( \sum_i w_i )^2 } \leq \frac{ 5^2 w }{ ( \sum_i w_i )^2 }
```

## Summary

By writing $n_w = m_w r + c_w$ in terms of the resampling ratio $r$,
the upper bound on the uncertainty of the weighted mean can be expressed as

```math
\sigma_{w}^2 \leq \frac{ \sum_w ( m_w r^2 + c_w^2 ) w }{ ( \sum_i w_i )^2 }
```

## Caveats

- This approach operates on unique values, which will only hold if there is no interpolation during resampling
