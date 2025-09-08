import pandas as pd


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


# tuple of [mean, std]
type annual_climatology = tuple[float, float]


def get_climatology(ts: pd.Series, variance: pd.Series) -> annual_climatology:
    """
    Calculate the climatology of a time series.

    Calculates the inverse-variance weighted mean

    Args:
        ts: Time series with a datetime index. Should have a annual frequency.
        variance: Variance of the time series.
    """
    # first check for zeros in variance (because we will divide by it)
    if (variance == 0).any():
        raise ValueError("Variance cannot contain zeros.")

    df = pd.DataFrame({"ts": ts, "variance": variance})
    
    mean = inverse_variance_weighted_mean(df)
    std_dev = std(df)
    return mean, std_dev


def get_standard_anomaly(ts: pd.Series, climatology: annual_climatology) -> pd.Series:
    """
    Calculate the standard anomaly of a time series.

    Args:
        ts: Time series with a datetime index. Should have a daily frequency.
        climatology: 

    Returns: A Series with the standard anomaly.
    """
    mean = climatology[0]
    std = climatology[1]

    z = (ts - mean) / std
    z.name = "z-score"

    return z


def get_climatology_bounds(
    ts: pd.DatetimeIndex,
    climatology: annual_climatology,
) -> pd.DataFrame:
    """
    Get the lower bound (mean - std) and upper bound (mean + std) of the climatology.

    Args:
        ts: Time series with a datetime index. Should have a daily frequency.
        climatology:

    Returns: a DataFrame with columns 'mean', 'lower bound', and 'upper bound',
        indexed by the original time series index.
    """
    mean = climatology[0]
    std = climatology[1]

    return pd.DataFrame({"mean": mean, "lower bound": mean - std, "upper bound": mean + std}, index=ts)
