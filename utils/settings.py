from typing import Literal

# this is a custom field in STAC collection metadata
# which provides some default visualization parameters for the zarr datacube
WPL_RENDER_KEY = "wpl:render"

POINT_OF_INTEREST_OPTS = {
    "marker": "+",
    "color": "red",
    "size": 14,
    "line_width": 2,
}

CATALOG_URL = "https://s3.waw3-2.cloudferro.com/swift/v1/wpl-stac/stac/catalog.json"


type RouteName = str
type RouteURL = str
type RouteParams = list[str]
type RouteInfo = tuple[RouteURL, RouteParams]


# URLs used to generate links between pages
# WARNING: when using `panel serve` these routes are defined by the filenames!
ROUTES: dict[RouteName, RouteInfo] = {
    "sites": ("/sites", []),
    "collections": ("/collections", ["site-id"]),
    "data": ("/data", ["site-id", "collection-id"]),
    "indicators": ("/indicators", ["site-id"]),
    "site-indicator": ("/site-indicator", ["site-id", "indicator-id"]),
}

# additional metadata key for STAC collection
WPL_BIOME_KEY = "wpl:biome"

type Biome = Literal["boreal", "temperate", "tropical"]


BIOME_COLOUR: dict[Biome, str] = {"boreal": "mediumturquoise", "temperate": "goldenrod", "tropical": "limegreen"}


# default is 330
SIDEBAR_WIDTH = 330


# should be an absolute path to the directory containing all site-level peat health indicators
SITE_LEVEL_PHI_DIR = os.environ.get("SITE_LEVEL_PHI_DIR", None)
