import panel as pn
from holoviews.plotting import list_cmaps


@pn.cache
def get_colour_maps() -> list[str]:
    """
    Get a list of available colour maps in HoloViews.
    """
    return list_cmaps()
