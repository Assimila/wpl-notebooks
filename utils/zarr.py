import datetime
import io

import cartopy.crs as ccrs
import geoviews as gv
import geoviews.feature as gf
import holoviews as hv
import pandas as pd
import panel as pn
import param
import pystac
import rasterio.crs
import rioxarray  # noqa: F401
import xarray as xr
from holoviews import streams
from matplotlib.colors import ListedColormap
from rasterio.io import MemoryFile

from . import settings
from .cog import Layer
from .colour_maps import get_colour_maps
from .utils import attach_stream_to_map, attach_stream_to_time_series
from .xyt import XYT, Extent


class ZarrDataset(pn.viewable.Viewer):
    """
    A panel Viewer for a Zarr datacube.

    It is assumed that you have two datasets,
    one chunked for spatial reads (xy_ds) and one chunked for temporal reads (ts_ds).

    In the map view, there is an option to overlay a peat extent mask,
    which must be provided in the same CRS.
    """

    location: XYT = param.ClassSelector(class_=XYT, label="Region of interest", allow_None=False, constant=True)  # type: ignore

    # these should be identical datasets, but chunked differently
    xy_ds: xr.Dataset = param.ClassSelector(
        class_=xr.Dataset, label="Datacube chunked for spatial reads", allow_None=False, constant=True
    )  # type: ignore
    ts_ds: xr.Dataset = param.ClassSelector(
        class_=xr.Dataset, label="Datacube chunked for temporal reads", allow_None=False, constant=True
    )  # type: ignore

    primary_var_name: str = param.Selector(objects=[])  # type: ignore
    uncertainty_var_name: str | None = param.Selector(objects=[])  # type: ignore

    # fallback to scalar uncertainty
    uncertainty_scalar_name: str | None = param.String(default=None, allow_None=True)  # type: ignore
    uncertainty_scalar_value: float | None = param.Number(default=None, allow_None=True)  # type: ignore

    colormap_name: str = param.Selector(objects=get_colour_maps(), allow_None=False)  # type: ignore
    colormap_max: float = param.Number(default=None, allow_None=False)  # type: ignore
    colormap_min: float = param.Number(default=None, allow_None=False)  # type: ignore

    # most appropriate date to visualize (from the time dimension of the dataset)
    date: datetime.datetime = param.Date(allow_None=False)  # type: ignore

    crs: ccrs.CRS = param.ClassSelector(
        class_=ccrs.CRS, default=None, allow_None=False, doc="native coordinate reference system", constant=True
    )  # type: ignore

    peat_extent_da: xr.DataArray | None = param.ClassSelector(
        class_=xr.DataArray, doc="peat extent map", allow_None=True, constant=True
    )  # type: ignore

    overlay_peat_extent: bool = param.Boolean(default=False, label="Overlay the WorldPeatland peat extent map")  # type: ignore

    def __init__(self, **params):
        super().__init__(**params)

        data_vars = list(self.xy_ds.data_vars)

        # set primary_var_name options from the Dataset
        self.param.primary_var_name.objects = data_vars
        self.param.primary_var_name.allow_None = False

        # set uncertainty_var_name options from the Dataset
        self.param.uncertainty_var_name.objects = data_vars
        self.param.uncertainty_var_name.allow_None = True

        # reassign values to trigger validation
        if "primary_var_name" in params:
            self.primary_var_name = params["primary_var_name"]
        else:
            self.primary_var_name = data_vars[0]

        if "uncertainty_var_name" in params:
            self.uncertainty_var_name = params["uncertainty_var_name"]
        else:
            self.uncertainty_var_name = None

        if "crs" not in params:
            # pull the CRS from xy_ds
            crs: rasterio.crs.CRS | None = self.xy_ds.rio.crs
            if crs is None:
                raise ValueError
            if not crs.is_epsg_code:
                raise NotImplementedError
            with param.edit_constant(self):
                self.crs = ccrs.epsg(crs.to_epsg())

    @staticmethod
    def from_pystac(
        collection: pystac.Collection, peat_extent: pystac.Collection | None = None, location: XYT | None = None
    ) -> "ZarrDataset":
        """
        Create a ZarrDataset from a pystac Collection

        Looks for a custom field `wpl:render` in the collection's metadata

        ```json
        {
            "assets": ["albedo.xy.zarr", "albedo.ts.zarr"],
            "primary_var_name": "albedo",
            "uncertainty_var_name": "albedo_std_dev",
            "uncertainty_scalar_name": None,
            "uncertainty_scalar_value": None,
            "colormap_name": "copper",
            "colormap_range": [0, 1]
        }
        ```
        """
        if location is None:
            extent = Extent.from_pystac(collection.extent)
            location = XYT(extent=extent)

        wpl_render = collection.extra_fields[settings.WPL_RENDER_KEY]

        xy_asset_key = next(a for a in wpl_render["assets"] if a.endswith(".xy.zarr"))
        ts_asset_key = next(a for a in wpl_render["assets"] if a.endswith(".ts.zarr"))

        xy_asset = collection.assets[xy_asset_key]
        ts_asset = collection.assets[ts_asset_key]

        xy_ds = xr.open_dataset(
            xy_asset.href,
            **xy_asset.ext.xarray.open_kwargs,  # type: ignore
        )
        ts_ds = xr.open_dataset(
            ts_asset.href,
            **ts_asset.ext.xarray.open_kwargs,  # type: ignore
        )

        peat_extent_da = load_peat_extent_from_stac(peat_extent)

        return ZarrDataset(
            location=location,
            xy_ds=xy_ds,
            ts_ds=ts_ds,
            primary_var_name=wpl_render["primary_var_name"],
            uncertainty_var_name=wpl_render["uncertainty_var_name"],
            uncertainty_scalar_name=wpl_render["uncertainty_scalar_name"],
            uncertainty_scalar_value=wpl_render["uncertainty_scalar_value"],
            colormap_name=wpl_render["colormap_name"],
            colormap_min=wpl_render["colormap_range"][0],
            colormap_max=wpl_render["colormap_range"][1],
            peat_extent_da=peat_extent_da,
        )

    @param.depends("location.date", watch=True, on_init=True)
    def select_date(self):
        """
        Given the date of the region of interest,
        find the most appropriate date to visualize from the time dimension of the dataset.

        Updates `self.date`
        """
        # this is a numpy datetime64[ns]
        t = self.xy_ds.time.sel(time=self.location.date, method="ffill")
        self.date = pd.Timestamp(t.values).to_pydatetime()

    def load_xy_slice(self) -> xr.DataArray:
        """
        Load a slice of the xy_ds dataset for the primary variable at the date of interest.
        """
        da = self.xy_ds[self.primary_var_name].sel(time=self.date)
        da.load()  # load data into memory
        return da

    def load_xy_slice_with_uncertainty(self) -> xr.Dataset:
        """
        Load a slice of the xy_ds dataset for the primary variable at the date of interest,
        including uncertainty if available.
        """
        variables = [self.primary_var_name]
        if self.uncertainty_var_name:
            variables.append(self.uncertainty_var_name)
        ds = self.xy_ds[variables].sel(time=self.date)
        ds.load()  # load data into memory
        return ds

    def load_ts_slice(self) -> pd.DataFrame:
        """
        Load a slice of the ts_ds dataset at the point of interest.
        Includes uncertainty if available.

        Returns:
            pandas DataFrame with columns for the primary variable
            and it's uncertainty (if available).
        """
        # transform the point of interest to the CRS of the dataset
        x, y = self.crs.transform_point(self.location.longitude, self.location.latitude, ccrs.PlateCarree())

        # load data
        da = self.ts_ds[self.primary_var_name].sel(x=x, y=y, method="nearest")
        da.load()  # load data into memory
        series = da.to_series()
        df = pd.DataFrame({self.primary_var_name: series})

        # uncertainty
        if self.uncertainty_var_name:
            da = self.ts_ds[self.uncertainty_var_name].sel(x=x, y=y, method="nearest")
            da.load()  # load data into memory
            if da.size == 1:
                # uncertainty layer does not have a time dimension
                df[self.uncertainty_var_name] = da.item()
            else:
                df[self.uncertainty_var_name] = da.to_series()
        elif self.uncertainty_scalar_name and self.uncertainty_scalar_value:
            df[self.uncertainty_scalar_name] = self.uncertainty_scalar_value
        else:
            pass  # no uncertainty available

        return df

    @param.depends(
        "date",
        "location.latitude",
        "location.longitude",
        "colormap_name",
        "colormap_min",
        "colormap_max",
        "overlay_peat_extent",
        watch=False,
    )
    def map_view(self) -> hv.Overlay:
        """
        GeoViews map plot of the primary variable @ the time of interest.
        Plotted in the native CRS of the dataset.
        Shows the bounding box of the extent.
        Plot the point of interest.
        """
        xy_slice = self.load_xy_slice()

        image = gv.Image(xy_slice, kdims=["x", "y"], crs=self.crs)
        image.opts(projection=self.crs)
        image.opts(colorbar=True, cmap=self.colormap_name, clim=(self.colormap_min, self.colormap_max))

        bbox = self.location.extent.spatial.polygon

        point = self.location.point()  # type: ignore

        overlay = [gf.ocean, gf.land, bbox, image]

        if self.peat_extent_da is not None:
            peat_extent_map = gv.Image(self.peat_extent_da, kdims=["x", "y"], crs=self.crs)
            peat_extent_map.opts(projection=self.crs)
            # toggle the alpha (transparency) based on the overlay_peat_extent parameter
            alpha = settings.PEAT_ALPHA if self.overlay_peat_extent else 0
            cmap = ListedColormap([settings.PEAT_COLOUR])
            peat_extent_map.opts(alpha=alpha, cmap=cmap, colorbar=False)
            overlay.append(peat_extent_map)

        overlay.append(point)
 
        return hv.Overlay(overlay)

    @param.depends(
        "date", "location.latitude", "location.longitude", "colormap_name", "colormap_min", "colormap_max", watch=False
    )
    def time_series_view(self) -> hv.Overlay:
        """
        Time series plot of the primary variable @ the point of interest.
        Includes envelope uncertainty if available.
        Plot the time of interest.
        """
        ts_df = self.load_ts_slice()
        data_series = ts_df[self.primary_var_name]

        # uncertainty envelope
        if self.uncertainty_var_name:
            uncertainty = ts_df[self.uncertainty_var_name]
        elif self.uncertainty_scalar_name:
            uncertainty = ts_df[self.uncertainty_scalar_name]
        else:
            uncertainty = None

        # list of plot elements to overlay
        elements = []

        if uncertainty is not None:
            area = hv.Area(
                # fill between (X, Y1, Y2)
                (data_series.index, (data_series - uncertainty), (data_series + uncertainty)),
                kdims=["time"],
                vdims=["lower bound", "upper bound"],
            )
            area.opts(alpha=0.4)
            elements.append(area)

        curve = hv.Curve(data_series, kdims=["time"], vdims=[self.primary_var_name])
        curve.opts(xlabel="date", ylabel=self.primary_var_name)
        curve.opts(framewise=True)  # allow ylims to update
        elements.append(curve)

        points = hv.Scatter(data_series, kdims=["time"], vdims=[self.primary_var_name])
        # color each point using the colormap
        points.opts(
            color=self.primary_var_name,
            cmap=self.colormap_name,
            clim=(self.colormap_min, self.colormap_max),
            size=5,
        )
        elements.append(points)

        # index with [] to preserve the length 1 time dimension
        data_at_date = data_series.loc[[pd.Timestamp(self.date)]]
        current_point = hv.Scatter(data_at_date, kdims=["time"], vdims=[self.primary_var_name])
        current_point.opts(**settings.POINT_OF_INTEREST_OPTS)
        elements.append(current_point)

        overlay = hv.Overlay(elements)

        return overlay

    def get_time_series_csv(self) -> io.StringIO:
        """
        Get the time series data (at the current point of interest) as a CSV.
        Suitable for downloading.
        """
        HEADER = "#"
        buffer = io.StringIO()
        buffer.write(f"{HEADER} Time series data for {self.primary_var_name}\n")
        buffer.write(f"{HEADER} latitude = {self.location.latitude}\n")
        buffer.write(f"{HEADER} longitude = {self.location.longitude}\n")
        ts_df = self.load_ts_slice()
        ts_df.to_csv(buffer)
        buffer.seek(0)  # rewind
        return buffer

    def get_xy_slice_geotiff(self) -> MemoryFile:
        """
        Get the map (at the current time of interest) as a GeoTIFF.
        Suitable for downloading.
        """
        ds = self.load_xy_slice_with_uncertainty()
        memory_file = MemoryFile()
        ds.rio.to_raster(memory_file.name)
        memory_file.seek(0)  # rewind
        return memory_file

    def widgets(self) -> pn.Param:
        params = ["colormap_name", "colormap_max", "colormap_min"]
        if self.peat_extent_da is not None:
            params.append("overlay_peat_extent")

        return pn.Param(
            self,
            parameters=params,
            show_name=False,
            widgets={"colormap_name": pn.widgets.AutocompleteInput},
        )

    def download_buttons(self):
        return pn.Column(
            pn.widgets.FileDownload(
                filename=param.rx("{var}-{date:%Y-%m-%d}.tiff").format(
                    var=self.param.primary_var_name, date=self.param.date
                ),
                callback=self.get_xy_slice_geotiff,
                button_style="solid",
                button_type="primary",
                icon="file-download",
            ),
            pn.widgets.FileDownload(
                filename=param.rx("{var}-time-series.csv").format(var=self.param.primary_var_name),
                callback=self.get_time_series_csv,
                button_style="solid",
                button_type="primary",
                icon="file-download",
            ),
        )

    def __panel__(self) -> pn.viewable.Viewable:
        """
        Build a visualisation of the dataset.

        GeoViews map plot of the primary variable @ the time of interest.
        Plotted in the native CRS of the dataset.
        Shows the bounding box of the extent.
        Plot the point of interest.

        Time series plot of the primary variable @ the point of interest.
        Includes uncertainty if available.
        Plot the time of interest.

        Tap / click on the plots to update the point of interest.
        """

        # IMPORTANT: plot size and layout must be set consistently twice!
        # 1. on the HoloViews object .opts(responsive=True)
        # 2. on the pn.pane.HoloViews(sizing_mode=...)

        map = gv.DynamicMap(self.map_view)
        tap = streams.Tap(rename={"x": "longitude", "y": "latitude"})
        tap.add_subscriber(self.location.maybe_update_lon_lat)
        map = attach_stream_to_map(tap, map)

        time_series = hv.DynamicMap(self.time_series_view)
        tap = streams.Tap()

        def on_click(x, y):
            # convert numpy datetime64 -> python
            t = pd.Timestamp(x).to_pydatetime()
            self.location.maybe_update_date(t)

        tap.add_subscriber(on_click)
        time_series = attach_stream_to_time_series(tap, time_series)
        time_series.opts(height=300, min_width=600, responsive=True)

        # there is an unfortunate bug https://github.com/holoviz/panel/issues/5070
        # which prevents align="center" on dynamically sized elements

        return pn.Column(
            pn.Row(
                pn.pane.HoloViews(
                    map,
                    width=600,
                    height=500,
                ),
            ),
            pn.Row(
                pn.pane.HoloViews(
                    time_series,
                    height=300,
                    min_width=600,
                    sizing_mode="stretch_width",
                ),
            ),
            pn.Row(
                self.download_buttons(),
            ),
            width_policy="max",
        )


def load_peat_extent_from_stac(collection: pystac.Collection | None) -> xr.DataArray | None:
    """
    Load a peat extent mask from a STAC Collection.
    Assumes that the STAC collection could be opened by COGDataset.
    """
    if collection is None:
        return None

    n_items = len(collection.get_item_links())
    if n_items != 1:
        raise ValueError("expected a single item in the collection")

    item = next(collection.get_items())

    if not item.ext.has("render"):
        raise ValueError("item does not implement the STAC render extension")

    default_render = item.ext.render.renders["default"]

    if len(default_render.assets) != 1:
        raise ValueError("expected a single asset in the default render")

    layer_id = default_render.assets[0]

    asset = item.get_assets(media_type=pystac.MediaType.COG)[layer_id]

    da = Layer.from_pystac(asset).da

    # mask non-peat with NaN
    return da.where(da == 1)
