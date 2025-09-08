import functools
import logging
import os
import pathlib
from collections import defaultdict
from typing import Annotated

import pandas as pd
import panel as pn
import pydantic
import rioxarray  # noqa: F401
import xarray as xr
from rasterio.errors import RasterioIOError

from .. import settings

logger = logging.getLogger(__name__)


class ImmutableModel(pydantic.BaseModel):
    model_config = pydantic.ConfigDict(frozen=True)


class InfoModel(ImmutableModel):
    """
    Encapsulates the info.json file for a site-level peat health indicator.
    """

    name: str
    description: str
    site_id: str
    default_variable_loading_name: str
    units: dict[str, str]  # mapping from variable name -> units


# constrain variable loading l_v to [-1, 1]
type loading = Annotated[float, pydantic.Field(ge=-1.0, le=1.0)]


class PredefinedVariableLoading(ImmutableModel):
    """
    Encapsulates a single variable loading configuration.
    for a site-level peat health indicator.

    The presence of a key in `optimal_values` indicates that the variable should be transformed
    to the absolute deviation from the specified value.
    """

    name: str
    description: str
    optimal_values: dict[str, float]
    variable_loadings: dict[str, loading]


class SiteLevelPHI(ImmutableModel):
    """
    Container for site-level (aggregated) peat health indicators.

    See `site-indicators.md` for more information.
    """

    # info.json
    info_file: pydantic.FilePath
    # path to peat_extent.tiff
    peat_extent_file: pydantic.FilePath
    # time_series.h5
    time_series_file: pydantic.FilePath
    # variable_loading/*.json
    variable_loading_dir: pydantic.DirectoryPath

    @functools.cached_property
    def info(self) -> InfoModel:
        with open(self.info_file, "r") as f:
            return InfoModel.model_validate_json(f.read())

    @pydantic.field_validator("info_file")
    @classmethod
    def validate_info_file(cls, v):
        with open(v, "r") as f:
            InfoModel.model_validate_json(f.read())
        return v

    # not cached because it may be large
    @property
    def peat_extent(self) -> xr.DataArray:
        """
        Try to load a sensible overview from the cloud optimized GeoTIFF
        """
        # don't try to render a array with a dimension > MAX_PIX
        MAX_PIX = 2048

        # first open the raw (high res) data
        overview_level = 0
        da = rioxarray.open_rasterio(
            self.peat_extent_file,
            overview_level=overview_level,
        )
        if not isinstance(da, xr.DataArray):
            raise ValueError("expected a DataArray")
        da = da.squeeze("band", drop=True)
        if da.rio.crs.to_epsg() != 4326:
            raise ValueError(f"peat_extent_file must have EPSG:4326 CRS, got {da.rio.crs}")
        nx = da.sizes["x"]
        ny = da.sizes["y"]

        # if too large, try higher overview levels
        while nx > MAX_PIX or ny > MAX_PIX:
            overview_level += 1
            try:
                da = rioxarray.open_rasterio(
                    self.peat_extent_file,
                    overview_level=overview_level,
                )
            except RasterioIOError:
                # overview level does not exist
                logger.warning(f"Could not find overview level {overview_level} in {self.peat_extent_file}")
                break
            if not isinstance(da, xr.DataArray):
                raise ValueError("expected a DataArray")
            da = da.squeeze("band", drop=True)
            nx = da.sizes["x"]
            ny = da.sizes["y"]
        
        return da

    @functools.cached_property
    def time_series(self) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
        """
        Load the time series data from the HDF5 file.

        Returns:
            A tuple of four DataFrames:
            - data: time series data
            - variance: variance of the time series data
            - annual_data: annual aggregated time series data
            - annual_variance: variance of the annual aggregated time series data
        """
        with pd.HDFStore(self.time_series_file, "r") as store:
            data = store["data"]
            if not isinstance(data, pd.DataFrame):
                raise ValueError("expected a DataFrame")
            variance = store["variance"]
            if not isinstance(variance, pd.DataFrame):
                raise ValueError("expected a DataFrame")
            annual_data = store["annual_data"]
            if not isinstance(annual_data, pd.DataFrame):
                raise ValueError("expected a DataFrame")
            annual_variance = store["annual_variance"]
            if not isinstance(annual_variance, pd.DataFrame):
                raise ValueError("expected a DataFrame")
        
        # check that all dataframes have the same columns
        columns = data.columns
        for df in [variance, annual_data, annual_variance]:
            if not df.columns.equals(columns):
                raise ValueError("All dataframes must have the same columns")
        
        # ensure index is the same between data and variance
        if not data.index.equals(variance.index):
            raise ValueError("data and variance must have the same index")
        
        # ensure index is the same between annual_data and annual_variance
        if not annual_data.index.equals(annual_variance.index):
            raise ValueError("annual_data and annual_variance must have the same index")
        
        # ensure all variance > 0
        if (variance <= 0).any().any():
            raise ValueError("variance must be non-negative")
        if (annual_variance <= 0).any().any():
            raise ValueError("annual_variance must be non-negative")

        return data, variance, annual_data, annual_variance
    
    @property
    def data(self) -> pd.DataFrame:
        return self.time_series[0]
    
    @property
    def variance(self) -> pd.DataFrame:
        return self.time_series[1]
    
    @property
    def annual_data(self) -> pd.DataFrame:
        return self.time_series[2]
    
    @property
    def annual_variance(self) -> pd.DataFrame:
        return self.time_series[3]
    
    @functools.cached_property
    def variable_loadings(self) -> dict[str, PredefinedVariableLoading]:
        """
        Load all predefined variable loadings from the variable_loading directory.

        Returns: mapping from loading name -> PredefinedVariableLoading instance.
        """
        ret = {}
        for item in os.listdir(self.variable_loading_dir):
            if not item.endswith(".json"):
                continue
            path = os.path.join(self.variable_loading_dir, item)
            with open(path, "r") as f:
                vloading = PredefinedVariableLoading.model_validate_json(f.read())
            ret[vloading.name] = vloading
        return ret

    @classmethod
    def from_directory(cls, directory: str) -> "SiteLevelPHI":
        """
        Create a SiteLevelPHI instance from a directory containing the required files.

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
        """
        if not os.path.isdir(directory):
            raise NotADirectoryError(directory)

        base = pathlib.Path(directory)

        return cls(
            info_file=base / "info.json",
            peat_extent_file=base / "peat_extent.tiff",
            time_series_file=base / "time_series.h5",
            variable_loading_dir=base / "variable_loading",
        )

@pn.cache
def all_site_level_peat_health_indicators() -> dict[str, dict[str, str]]:
    """
    Search `SITE_LEVEL_PHI_DIR` for site-level peat health indicators.

    Returns: mapping from site-id -> extent name -> subdirectory.
    """
    if settings.SITE_LEVEL_PHI_DIR is None:
        raise ValueError("SITE_LEVEL_PHI_DIR is not set")

    if not os.path.isdir(settings.SITE_LEVEL_PHI_DIR):
        raise NotADirectoryError(settings.SITE_LEVEL_PHI_DIR)

    ret = defaultdict(dict)

    for item in os.listdir(settings.SITE_LEVEL_PHI_DIR):
        item_path = os.path.join(settings.SITE_LEVEL_PHI_DIR, item)
        if not os.path.isdir(item_path):
            continue
        subdir = item_path
        info_file = os.path.join(subdir, "info.json")
        if not os.path.isfile(info_file):
            continue
        with open(info_file, "r") as f:
            info = InfoModel.model_validate_json(f.read())
        ret[info.site_id][info.name] = subdir

    return ret


@pn.cache
def get_phi(site_id: str, extent_name: str) -> str | None:
    """
    Returns a directory for a valid site-level peat health indicator,
    or None if not found.
    """
    phis = all_site_level_peat_health_indicators()
    try:
        return phis[site_id][extent_name]
    except KeyError:
        return None
