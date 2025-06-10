import param
import pystac

from . import utils

root_catalog = utils.get_root_catalog()
sites = {site.id: site for site in utils.get_sub_catalogs(root_catalog)}


class UrlQueryParams(param.Parameterized):
    """
    param Parameterized class to sync with URL query parameters.

    https://panel.holoviz.org/how_to/state/url.html

    Usage:

    ```python
    query_params = UrlQueryParams()
    pn.state.location.sync(
        query_params,
        {
            "site_id": "site-id",
            "collection_id": "collection-id"
        }
    )
    ```
    """

    site_id: str = param.String()  # type: ignore
    collection_id: str = param.String()  # type: ignore

    site: pystac.Catalog | None = param.ClassSelector(class_=pystac.Catalog, default=None, allow_None=True)  # type: ignore

    collection: pystac.Collection | None = param.ClassSelector(class_=pystac.Collection, default=None, allow_None=True)  # type: ignore

    @param.depends("site_id", watch=True)
    def maybe_update_site(self):
        try:
            self.site = sites[self.site_id]
        except KeyError:
            self.site = None
        # reset collection if site changes
        self.collection = None

    @param.depends("collection_id", watch=True)
    def maybe_update_collection(self):
        if self.site is None:
            self.collection = None
            return
        collections = utils.get_collections(self.site)
        try:
            self.collection = next(c for c in collections if c.id == self.collection_id)
        except StopIteration:
            self.collection = None
