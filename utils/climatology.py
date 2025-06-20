import pandas as pd


def day_of_year(t: pd.Timestamp) -> int:
    """
    Returns a leap-year insensitive day of year.
    Both 28 and 29 Feb are considered as day 59.
    """
    if not t.is_leap_year:
        return t.dayofyear
    elif t.month > 2:
        return t.dayofyear - 1
    elif t.month == 2 and t.day == 29:
        return 59
    else:
        return t.dayofyear


def drop_29_feb(df: pd.DataFrame) -> pd.DataFrame:
    """
    Drops 29 February from a DataFrame with a datetime index.
    """
    if not isinstance(df.index, pd.DatetimeIndex):
        raise ValueError("DataFrame index must be a DatetimeIndex")
    return df[~((df.index.month == 2) & (df.index.day == 29))]


def inverse_variance_weighted_mean(group: pd.DataFrame) -> float:
    """
    Calculate the inverse-variance weighted mean

    Args:
        group: A DataFrame with columns 'ts' and 'variance'.
    """
    weights = 1 / group["variance"]
    return (group["ts"] * weights).sum() / weights.sum()


def std(group: pd.DataFrame) -> float:
    """
    Calculate the standard deviation of a group.

    Args:
        group: A DataFrame with columns 'ts' and 'variance'.
    """
    return group["ts"].std()


def daily_climatology(ts: pd.Series, variance: pd.Series) -> pd.DataFrame:
    """
    Calculate the daily climatology of a time series.

    Drops 29 February.

    Calculates the inverse-variance weighted mean

    Args:
        ts: Time series with a datetime index. Should have a daily frequency.
        variance: Variance of the time series.

    Returns: A DataFrame with columns 'mean' and 'std' indexed by 365 day of year.
    """
    # first check for zeros in variance (because we will divide by it)
    if (variance == 0).any():
        raise ValueError("Variance cannot contain zeros.")

    df = pd.DataFrame({"ts": ts, "variance": variance})
    df = drop_29_feb(df)
    df["doy"] = df.index.map(day_of_year)

    groups = df.groupby("doy")

    # Apply the aggregate function to each group as a whole (not per column)
    mean = groups.apply(inverse_variance_weighted_mean)
    _std = groups.apply(std)

    return pd.DataFrame({"mean": mean, "std": _std})


def standard_anomaly(ts: pd.Series, climatology: pd.DataFrame) -> pd.Series:
    """
    Calculate the standard anomaly of a time series.

    Args:
        ts: Time series with a datetime index. Should have a daily frequency.
        climatology: DataFrame with columns 'mean' and 'std' indexed by 365 day of year.

    Returns: A Series with the standard anomaly.
    """
    if not isinstance(ts.index, pd.DatetimeIndex):
        raise ValueError("Time series index must be a DatetimeIndex")

    doy: pd.Index = ts.index.map(day_of_year)

    # Series index by doy
    mean = climatology.loc[doy, "mean"]
    std = climatology.loc[doy, "std"]

    # apply ts.index to mean and std
    mean.index = ts.index
    std.index = ts.index

    return (ts - mean) / std


def get_climatology_bounds(
    ts: pd.DatetimeIndex,
    climatology: pd.DataFrame,
) -> pd.DataFrame:
    """
    Get the lower bound (mean - std) and upper bound (mean + std) of the climatology.

    Args:
        ts: Time series with a datetime index. Should have a daily frequency.
        climatology: DataFrame with columns 'mean' and 'std' indexed by 365 day of year.

    Returns: a DataFrame with columns 'mean', 'lower bound', and 'upper bound',
        indexed by the original time series index.
    """
    doy: pd.Index = ts.map(day_of_year)

    # Series index by doy
    mean = climatology.loc[doy, "mean"]
    std = climatology.loc[doy, "std"]

    # apply the original ts index
    mean.index = ts
    std.index = ts

    return pd.DataFrame({
        "mean": mean,
        "lower bound": mean - std, 
        "upper bound": mean + std
    })
