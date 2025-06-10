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
ROUTES: dict[RouteName, RouteInfo] = {
    "index": ("/", []),
    "indicators": ("/indicators", ["site-id"]),
    "data": ("/data", ["site-id", "collection-id"]),
    "collections": ("/collections", ["site-id"]),
}

# additional metadata key for STAC collection
WPL_BIOME_KEY = "wpl:biome"

type Biome = Literal["boreal", "temperate", "tropical"]


BIOME_COLOUR: dict[Biome, str] = {"boreal": "teal", "temperate": "darkgoldenrod", "tropical": "green"}
