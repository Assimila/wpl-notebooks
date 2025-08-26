import logging

import pystac

from . import settings, utils
from .cog import COGDataset
from .settings import WPL_RENDER_KEY
from .zarr import ZarrDataset

logger = logging.getLogger(__name__)


# If this gets any more complex
# refactor these classes into a proper OOP hierarchy.


def map_collection_to_dataset(collection: pystac.Collection) -> ZarrDataset | COGDataset | None:
    """
    Map a STAC Collection to a dataset type.

    In the World Peatland STAC, most collections are type-1 (Zarr).
    But there are a few collections of type-2 (COG) that we need to treat differently.
    Note that this application is not a generic STAC client.

    # ZarrDataset

    - collection has no items
    - collection has 2 direct children (assets) which are Zarr datacubes
    - one Zarr datacube is optimised for spatial reads, with suffix ".xy.zarr"
    - the other Zarr datacube is optimised for time series reads has suffix ".ts.zarr"
    - the collection has a custom metadata key `wpl:render`

    # COGDataset

    - collection has a single item
    - item has the STAC render extension with a "default" key
    - item has metadata `datetime=null`, but instead has a range of validity from `start_datetime` to `end_datetime`
    - item should have a small number of assets, which are cloud optimized geotiffs (COGs)

    Returns:
        None if unable to parse the collection into a dataset type.
        Or if there is an unexpected failure.
    """
    n_items = len(collection.get_item_links())
    # number of Zarr assets that are direct children of the collection
    n_zarr = len(collection.get_assets(media_type=pystac.MediaType.ZARR))
    has_render_key = WPL_RENDER_KEY in collection.extra_fields

    # look for a peat extent collection to use as an optional map layer
    # should be a sibling STAC collection in the same catalog
    peat_extent_collection: pystac.Collection | None = None
    if collection.id != settings.PEAT_EXTENT_COLLECTION_ID:
        site_catalog = collection.get_parent()
        if site_catalog is not None:
            collections = utils.get_collections(site_catalog)
            try:
                peat_extent_collection = next(c for c in collections if c.id == settings.PEAT_EXTENT_COLLECTION_ID)
            except StopIteration:
                pass

    if n_items == 0 and n_zarr >= 2 and has_render_key:
        try:
            return ZarrDataset.from_pystac(collection, peat_extent=peat_extent_collection)
        except Exception:
            logger.exception("Failed to create ZarrDataset from collection", collection)
            return None
    elif n_items == 1 and n_zarr == 0 and not has_render_key:
        try:
            return COGDataset.from_pystac(collection, peat_extent=peat_extent_collection)
        except Exception:
            logger.exception("Failed to create COGDataset from collection", collection)
            return None
    else:
        return None
