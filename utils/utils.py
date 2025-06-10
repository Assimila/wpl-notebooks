import geoviews as gv
import holoviews as hv
from holoviews import streams


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
