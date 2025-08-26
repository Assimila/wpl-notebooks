import logging
from dataclasses import dataclass

import cartopy.crs as ccrs
import geoviews as gv
import geoviews.feature as gf
import holoviews as hv
import panel as pn
import param
import pystac
import rasterio.crs
import rioxarray  # noqa: F401
import xarray as xr
from holoviews import streams

from . import settings, utils
from .colour_maps import get_colour_maps
from .utils import attach_stream_to_map
from .xyt import XY, Extent

logger = logging.getLogger(__name__)


def fix_units(da: xr.DataArray):
    """
    Fixes the type of the `units` attribute.
    If this is an integer then HoloViews crashes!?
    """
    if "units" in da.attrs and type(da.attrs["units"]) is int:
        logger.debug("Fixing units attribute type from int to str")
        da.attrs["units"] = str(da.attrs["units"])


@dataclass
class Layer:
    da: xr.DataArray
    href: str

    @staticmethod
    def from_pystac(asset: pystac.Asset) -> "Layer":
        """
        Create a Layer from a STAC asset.
        """
        da = xr.open_dataarray(asset.href, engine="rasterio", default_name=asset.title)
        if da.sizes["band"] != 1:
            raise ValueError("Expected a single bad")
        da = da.squeeze("band", drop=True)
        fix_units(da)
        return Layer(da=da, href=asset.href)


class COGDataset(pn.viewable.Viewer):
    """
    A panel Viewer for a STAC collection composed of a single item with a small number of assets.
    This item is expected to have the STAC render extension.
    And the assets are expected to be cloud optimized GeoTIFFs (COGs).

    This sort collection does not have a time dimension - the item has `datetime=null`,
    but instead has a range of validity from `start_datetime` to `end_datetime`.

    `layers` are expected to be single-band DataArrays, with (y, x) dimensions.
    """

    location: XY = param.ClassSelector(class_=XY, label="Region of interest", allow_None=False, constant=True)  # type: ignore

    layers: dict[str, Layer] = param.Dict(
        allow_None=False, default=dict(), doc="mapping from some key to Layer", constant=True
    )  # type: ignore

    layer_id: str = param.Selector(objects=[], allow_None=False, doc="selected layer id")  # type: ignore

    colormap_name: str = param.Selector(objects=get_colour_maps(), allow_None=False)  # type: ignore
    colormap_max: float = param.Number(default=None, allow_None=False)  # type: ignore
    colormap_min: float = param.Number(default=None, allow_None=False)  # type: ignore

    crs: ccrs.CRS = param.ClassSelector(
        class_=ccrs.CRS, default=None, allow_None=False, doc="native coordinate reference system", constant=True
    )  # type: ignore

    def __init__(self, **params):
        super().__init__(**params)

        # set layer_id options from layers
        self.param.layer_id.objects = self.layers.keys()

        # reassign values to trigger validation
        if "layer_id" in params:
            self.layer_id = params["layer_id"]
        else:
            # pick the first layer
            self.layer_id = next(iter(self.layers.keys()))

        if "crs" not in params:
            # try pull the CRS from primary_var_name
            da = self.layers[self.layer_id].da
            crs: rasterio.crs.CRS | None = da.rio.crs
            if crs is None:
                raise ValueError
            if not crs.is_epsg_code:
                raise NotImplementedError
            with param.edit_constant(self):
                self.crs = ccrs.epsg(crs.to_epsg())

        utils.fix_crs_extent(self.crs)

    @staticmethod
    def from_pystac(collection: pystac.Collection, location: XY | None = None) -> "COGDataset":
        """
        Create a COGDataset from a STAC collection.

        - collection has a single item
        - item has the STAC render extension with a "default" key
        - item should have a small number of assets, which are cloud optimized geotiffs (COGs)
        """
        if location is None:
            extent = Extent.from_pystac(collection.extent)
            location = XY(extent=extent)

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

        colormap_name = default_render.colormap_name

        if default_render.rescale is None or len(default_render.rescale) != 1:
            raise ValueError("expected a single rescale in the default render")

        colormap_min, colormap_max = default_render.rescale[0]

        assets = item.get_assets(media_type=pystac.MediaType.COG)

        layers = {asset_key: Layer.from_pystac(asset) for asset_key, asset in assets.items()}

        return COGDataset(
            location=location,
            layers=layers,
            layer_id=layer_id,
            colormap_name=colormap_name,
            colormap_max=colormap_max,
            colormap_min=colormap_min,
        )

    @param.depends(
        "layer_id",
        "location.latitude",
        "location.longitude",
        "colormap_name",
        "colormap_min",
        "colormap_max",
        watch=False,
    )
    def map_view(self) -> hv.Overlay:
        """
        GeoViews map plot of the primary variable @ the time of interest.
        Plotted in the native CRS of the dataset.
        Shows the bounding box of the extent.
        Plot the point of interest.
        """
        da = self.layers[self.layer_id].da

        image = gv.Image(da, kdims=["x", "y"], crs=self.crs)
        image.opts(projection=self.crs)
        image.opts(colorbar=True, cmap=self.colormap_name, clim=(self.colormap_min, self.colormap_max))
        image.opts(clabel=utils.cf_units(da))

        bbox = self.location.extent.spatial.polygon

        point = self.location.point()  # type: ignore

        overlay = [
            gf.ocean(scale=settings.GEOVIEWS_FEATURES_SCALE),
            gf.land(scale=settings.GEOVIEWS_FEATURES_SCALE),
            bbox,
            image,
            point
        ]

        return hv.Overlay(overlay)

    def widgets(self) -> pn.Param:
        return pn.Param(
            self,
            parameters=["layer_id", "colormap_name", "colormap_min", "colormap_max"],
            show_name=False,
            widgets={"colormap_name": pn.widgets.AutocompleteInput},
        )

    @param.depends("layer_id", watch=False)
    def download_link(self) -> pn.pane.Markdown:
        href = self.layers[self.layer_id].href
        return pn.pane.Markdown(f"🔗 [Download this data]({href})")

    def __panel__(self) -> pn.viewable.Viewable:
        """
        Build a visualisation of the dataset.

        GeoViews map plot of the selected layer_id.
        Plotted in the native CRS of the dataset.
        Shows the bounding box of the extent.
        Plot the point of interest.

        Tap / click on the plots to update the point of interest.
        """

        # IMPORTANT: plot size and layout must be set consistently twice!
        # 1. on the HoloViews object .opts(responsive=True)
        # 2. on the pn.pane.HoloViews(sizing_mode=...)

        map = gv.DynamicMap(self.map_view)
        tap = streams.Tap(rename={"x": "longitude", "y": "latitude"})
        tap.add_subscriber(self.location.maybe_update_lon_lat)
        map = attach_stream_to_map(tap, map)

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
            pn.Row(self.download_link),
            width_policy="max",
        )
