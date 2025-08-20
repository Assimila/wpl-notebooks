import copy
import functools
import itertools
import urllib.parse
from typing import Callable, Iterator, get_args

import cartopy.crs as ccrs
import geoviews as gv
import holoviews as hv
import panel as pn
import pystac
from holoviews import streams

from . import settings


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
    return list(catalog.get_collections())


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
