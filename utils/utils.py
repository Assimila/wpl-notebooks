import copy
import functools
import itertools
import logging
import urllib.parse
from dataclasses import dataclass
from typing import Callable, Iterator, get_args

import cartopy.crs as ccrs
import geoviews as gv
import holoviews as hv
import panel as pn
import pystac
import xarray as xr
from holoviews import streams

from . import settings

logger = logging.getLogger(__name__)


def attach_stream_to_map(steam: streams.Stream, dynamic_map: gv.DynamicMap) -> gv.Overlay:
    """
    This is a workaround for https://github.com/holoviz/holoviews/issues/3533

    We would like to directly subscribe to events from the dynamic map,
    but sometimes these event do not trigger.
    """
    # this is an empty element
    event_source = gv.Points([])
    steam.source = event_source
    return event_source * dynamic_map


def attach_stream_to_time_series(steam: streams.Stream, dynamic_map: hv.DynamicMap) -> hv.Overlay:
    """
    This is a workaround for https://github.com/holoviz/holoviews/issues/3533

    We would like to directly subscribe to events from the dynamic map,
    but sometimes these event do not trigger.
    """
    # this is an empty element
    event_source = hv.Scatter([])
    steam.source = event_source
    return event_source * dynamic_map


def get_url(route_name: str, kwargs: dict | None = None) -> str:
    """
    Get the URL for a named route, which may expect query parameters.
    """
    if kwargs is None:
        kwargs = {}
    url, params = settings.ROUTES[route_name]
    if len(params) == 0:
        return url
    qstring = urllib.parse.urlencode({k: kwargs[k] for k in params})
    return f"{url}?{qstring}"


@pn.cache
def get_root_catalog() -> pystac.Catalog:
    return pystac.read_file(settings.CATALOG_URL)  # type: ignore


def catalog_hash(catalog: pystac.Catalog) -> bytes:
    hash = catalog.id + " " + catalog.self_href
    return hash.encode("utf-8")


@pn.cache(hash_funcs={pystac.Catalog: catalog_hash})
def get_sub_catalogs(catalog: pystac.Catalog) -> list[pystac.Catalog]:
    return [child for child in catalog.get_children() if child.STAC_OBJECT_TYPE == pystac.STACObjectType.CATALOG]


@pn.cache
def get_site_catalog(site_id: str) -> pystac.Catalog:
    """
    Get the site catalog for a given site ID.
    """
    root_catalog = get_root_catalog()
    child = root_catalog.get_child(site_id)
    if child is None or child.STAC_OBJECT_TYPE != pystac.STACObjectType.CATALOG:
        raise ValueError(f"Site catalog for {site_id} not found.")
    return child


@pn.cache(hash_funcs={pystac.Catalog: catalog_hash})
def get_collections(catalog: pystac.Catalog) -> list[pystac.Collection]:
    """
    Get all collections in a catalog.

    Sorts according to collection title,
    with a caveat that some collections have a title such as "Albedo - detrended",
    which should be sorted directly after "Albedo".
    """
    SUFFIX = " - detrended"
    collections = list(catalog.get_collections())
    def sort_key(c: pystac.Collection):
        title = c.title
        if title is None:
            raise ValueError(f"Collection {c.id} has no title")
        has_suffix = title.endswith(SUFFIX)
        base_title = title[:-len(SUFFIX)] if has_suffix else title
        return (base_title, has_suffix)
    return sorted(collections, key=sort_key)


def get_biome(site: pystac.Catalog) -> settings.Biome | None:
    """Look for a `wpl:biome` key in catalog metadata"""
    if settings.WPL_BIOME_KEY in site.extra_fields:
        biome = site.extra_fields[settings.WPL_BIOME_KEY].lower()
        if biome in get_args(settings.Biome.__value__):
            return biome
    return None


def get_biome_colour(biome: str | None) -> str:
    """
    Get the colour associated with a biome.
    """
    try:
        return settings.BIOME_COLOUR[biome]  # type: ignore
    except KeyError:
        return "grey"  # default to grey if biome not found


def colours() -> Iterator[str]:
    """
    Yields colours from the default Holoviews colour cycle infinitely.
    """
    colours = hv.Cycle.default_cycles["Category10"]
    yield from itertools.cycle(colours)


def deepcopy[**P, R](func: Callable[P, R]) -> Callable[P, R]:
    """
    Decorator that returns a deepcopy of the inner function's return value.
    """

    @functools.wraps(func)
    def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
        result = func(*args, **kwargs)
        return copy.deepcopy(result)

    return wrapper


def fix_crs_extent(crs: ccrs.CRS):
    """
    FIX: GeoViews will not render outside of the CRS bounds.
    Additionally, the cost of imposing this masking is significant (multiple seconds).

    Central Kalimantan sits on the border between UTM 49S and UTM 50S.
    So we need to extend the bounds of the CRS a little,
    even though this results in greater spatial distortion.
    """
    if crs.to_epsg() == 32750:  # UTM 50S
        # extend the bounds to the west
        x0, x1, y0, y1 = crs.bounds
        crs.bounds = (
            x0 - 50000,
            x1,
            y0,
            y1,
        )


def cf_units(da: xr.DataArray) -> str | None:
    """
    Extract CF-compliant units from attributes.
    """
    units = None
    if "units" in da.attrs:
        units = da.attrs["units"]
    if units == "1":
        # "1" implies a fractional quantity with no units
        units = None
    return units


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
