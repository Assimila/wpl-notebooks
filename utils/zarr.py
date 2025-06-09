import datetime

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
from holoviews.plotting import list_cmaps

from .xyt import POINT_OF_INTEREST_OPTS, XYT, attach_stream_to_map, attach_stream_to_time_series


class ZarrDataset(pn.viewable.Viewer):
    """
    A panel Viewer for a Zarr datacube.

    It is assumed that you have two datasets,
    one chunked for spatial reads (xy_ds) and one chunked for temporal reads (ts_ds).
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
    uncertainty_scalar: float | None = param.Number(default=None, allow_None=True)  # type: ignore

    colormap_name: str = param.Selector(objects=list_cmaps(), allow_None=False)  # type: ignore
    colormap_min: float = param.Number(default=None, allow_None=False)  # type: ignore
    colormap_max: float = param.Number(default=None, allow_None=False)  # type: ignore

    # most appropriate date to visualize (from the time dimension of the dataset)
    # given the region of interest self.location.date
    date: datetime.datetime = param.Date(allow_None=False)  # type: ignore

    crs: ccrs.CRS = param.ClassSelector(class_=ccrs.CRS, default=None, allow_None=False, constant=True)  # type: ignore

    loading = param.Boolean(default=False, doc="Indicates whether we are waiting for data to load")  # type: ignore

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
    def from_pystac(location: XYT, collection: pystac.Collection) -> "ZarrDataset":
        """
        Create a ZarrDataset from a pystac Collection

        Looks for a custom field `wpl:render` in the collection's metadata

        ```json
        {
            "assets": ["albedo.xy.zarr", "albedo.ts.zarr"],
            "colormap_name": "copper",
            "colormap_range": [0, 1],
            "primary_var_name": "albedo",
            "uncertainty_scalar": None,
            "uncertainty_var_name": "albedo_std_dev"
        }
        ```
        """

        # this is a custom field which provides some default visualization parameters for the zarr datacube
        WPL_RENDER_KEY = "wpl:render"

        if WPL_RENDER_KEY not in collection.extra_fields:
            raise ValueError(f"Collection {collection.id} does not have the required field {WPL_RENDER_KEY}")

        wpl_render = collection.extra_fields[WPL_RENDER_KEY]

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

        return ZarrDataset(
            location=location,
            xy_ds=xy_ds,
            ts_ds=ts_ds,
            primary_var_name=wpl_render["primary_var_name"],
            uncertainty_var_name=wpl_render["uncertainty_var_name"],
            uncertainty_scalar=wpl_render["uncertainty_scalar"],
            colormap_name=wpl_render["colormap_name"],
            colormap_min=wpl_render["colormap_range"][0],
            colormap_max=wpl_render["colormap_range"][1],
        )

    @param.depends("location.date", watch=True, on_init=True)
    def select_date(self):
        """
        Given the date of the region of interest,
        find the most appropriate date to visualize from the time dimension of the dataset.
        """
        # this is a numpy datetime64[ns]
        t = self.xy_ds.time.sel(time=self.location.date, method="ffill")
        self.date = pd.Timestamp(t.values).to_pydatetime()

    @param.depends("date", "location.latitude", "location.longitude", watch=False)
    def map_view(self) -> hv.Overlay:
        """
        GeoViews map plot of the primary variable @ the time of interest.
        Shows the bounding box of the extent.
        Plot the point of interest.
        """
        with self.param.update(loading=True):
            _slice = self.xy_ds[self.primary_var_name].sel(time=self.date)
            # manually trigger loading the data from the zarr store
            _slice.load()

            image = gv.Image(_slice, kdims=["x", "y"], crs=self.crs)
            image.opts(colorbar=True, cmap=self.colormap_name, clim=(self.colormap_min, self.colormap_max))

            bbox = self.location.extent.spatial.polygon

            point = self.location.point()  # type: ignore

            overlay = gf.ocean * gf.land * bbox * image * point

            return overlay

    @param.depends("date", "location.latitude", "location.longitude", watch=False)
    def time_series_view(self) -> hv.Overlay:
        """
        Time series plot of the primary variable @ the point of interest.
        Includes envelope uncertainty if available.
        Plot the time of interest.
        """
        with self.param.update(loading=True):
            x, y = self.crs.transform_point(self.location.longitude, self.location.latitude, ccrs.PlateCarree())
            _slice = self.ts_ds[self.primary_var_name].sel(x=x, y=y, method="nearest")
            # manually trigger loading the data from the zarr store
            _slice.load()

            # uncertainty envelope
            if self.uncertainty_var_name:
                uncertainty = self.ts_ds[self.uncertainty_var_name].sel(x=x, y=y, method="nearest")
                # manually trigger loading the data from the zarr store
                uncertainty.load()
            elif self.uncertainty_scalar is not None:
                uncertainty = self.uncertainty_scalar
            else:
                uncertainty = None

            # list of plot elements to overlay
            elements = []

            if uncertainty is not None:
                area = hv.Area(
                    # fill between (X, Y1, Y2)
                    (_slice.time, (_slice - uncertainty), (_slice + uncertainty)),
                    kdims=["time"],
                    vdims=["lower bound", "upper bound"],
                )
                area.opts(alpha=0.4)
                elements.append(area)

            curve = hv.Curve(_slice, kdims=["time"])
            curve = curve.opts(
                framewise=True,
            )
            elements.append(curve)

            points = hv.Scatter(_slice, kdims=["time"], vdims=[self.primary_var_name])
            # color each point using the colormap
            points = points.opts(
                color=self.primary_var_name,
                cmap=self.colormap_name,
                clim=(self.colormap_min, self.colormap_max),
                size=6,
            )
            elements.append(points)

            # index with [] to preserve the length 1 time dimension
            data_at_date = _slice.sel(time=[self.date])
            current_point = hv.Scatter(data_at_date, kdims=["time"], vdims=[self.primary_var_name])
            current_point.opts(**POINT_OF_INTEREST_OPTS)
            elements.append(current_point)

            overlay = hv.Overlay(elements)

            return overlay

    def __panel__(self) -> pn.viewable.Viewable:
        """
        Build a visualisation of the dataset.

        GeoViews map plot of the primary variable @ the time of interest.
        Shows the bounding box of the extent.
        Plot the point of interest.

        Time series plot of the primary variable @ the point of interest.
        Includes uncertainty if available.
        Plot the time of interest.

        Tap / click on the plots to update the point of interest.
        """
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
        timeseries = attach_stream_to_time_series(tap, time_series)

        # there seems to be a strange bug with sizing_mode="stretch_width" on HoloViews pane
        # hence use of spacers below

        return pn.Column(
            pn.Row(
                pn.Spacer(sizing_mode="stretch_both"),
                pn.pane.HoloViews(
                    map,
                    width=400,
                    height=300,
                ),
                pn.Spacer(sizing_mode="stretch_both"),
            ),
            pn.Row(
                pn.Spacer(sizing_mode="stretch_both"),
                pn.pane.HoloViews(
                    timeseries,
                    width=800,
                    height=250,
                ),
                pn.Spacer(sizing_mode="stretch_both"),
            ),
            width_policy="max",
            loading=self.param.loading,
        )
