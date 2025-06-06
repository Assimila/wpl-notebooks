import datetime

import cartopy.crs as ccrs
import geoviews as gv
import holoviews as hv
import panel as pn
import param
import pystac
from holoviews import streams


class SpatialExtent(param.Parameterized):
    """A bounding box in decimal degrees"""

    longitude_min: float = param.Number(default=0, bounds=(0, 360), allow_None=False, constant=True)  # type: ignore
    longitude_max: float = param.Number(default=0, bounds=(0, 360), allow_None=False, constant=True)  # type: ignore
    latitude_min: float = param.Number(default=0, bounds=(-90, 90), allow_None=False, constant=True)  # type: ignore
    latitude_max: float = param.Number(default=0, bounds=(-90, 90), allow_None=False, constant=True)  # type: ignore

    @property
    def center(self) -> tuple[float, float]:
        """Returns the midpoint of the bounding box (longitude, latitude)"""
        return ((self.longitude_min + self.longitude_max) / 2, (self.latitude_min + self.latitude_max) / 2)

    @property
    def polygon(self) -> gv.Polygons:
        """Returns a Polygons object representing the spatial bounding box"""
        # right-hand
        polygons = gv.Polygons(
            [
                [
                    (self.longitude_min, self.latitude_min),
                    (self.longitude_min, self.latitude_max),
                    (self.longitude_max, self.latitude_max),
                    (self.longitude_max, self.latitude_min),
                    (self.longitude_min, self.latitude_min),
                ]
            ],
            kdims=["longitude", "latitude"],
        )
        polygons.opts(fill_alpha=0, line_color="blue", line_width=2)
        return polygons

    @staticmethod
    def from_pystac(spatial_extent: pystac.SpatialExtent) -> "SpatialExtent":
        """
        Create a SpatialExtent object from STAC JSON.
        """
        bbox = spatial_extent.bboxes[0]
        if len(bbox) != 4:
            raise ValueError()
        return SpatialExtent(
            longitude_min=bbox[0],
            latitude_min=bbox[1],
            longitude_max=bbox[2],
            latitude_max=bbox[3],
        )


class TemporalExtent(param.Parameterized):
    t_min: datetime.datetime = param.Date(default=datetime.datetime(2000, 1, 1), allow_None=False, constant=True)  # type: ignore
    t_max: datetime.datetime = param.Date(default=datetime.datetime(2024, 12, 31), allow_None=False, constant=True)  # type: ignore

    @staticmethod
    def from_pystac(temporal_extent: pystac.TemporalExtent) -> "TemporalExtent":
        """
        Create a TemporalExtent object from STAC JSON.
        """
        t_min, t_max = temporal_extent.intervals[0]
        if t_min is None:
            raise ValueError
        if t_min.tzinfo is not None:
            # convert to tz-naive UTC
            t_min = t_min.astimezone(datetime.timezone.utc).replace(tzinfo=None)
        if t_max is None:
            raise ValueError
        if t_max.tzinfo is not None:
            # convert to tz-naive UTC
            t_max = t_max.astimezone(datetime.timezone.utc).replace(tzinfo=None)
        return TemporalExtent(t_min=t_min, t_max=t_max)


class Extent(param.Parameterized):
    """
    Mirrors STAC catalog extent.

    https://github.com/radiantearth/stac-spec/blob/master/collection-spec/collection-spec.md#extents
    """

    spatial: SpatialExtent = param.ClassSelector(
        class_=SpatialExtent, default=SpatialExtent(), allow_None=False, constant=True
    )  # type: ignore
    temporal: TemporalExtent = param.ClassSelector(
        class_=TemporalExtent, default=TemporalExtent(), allow_None=False, constant=True
    )  # type: ignore

    @staticmethod
    def from_pystac(extent: pystac.Extent) -> "Extent":
        """
        Create an Extent object from STAC JSON.
        """
        spatial = SpatialExtent.from_pystac(extent.spatial)
        temporal = TemporalExtent.from_pystac(extent.temporal)
        return Extent(spatial=spatial, temporal=temporal)


class XYT(pn.viewable.Viewer):
    """
    A utility Parameterized class that contains

    - a point of interest (latitude, longitude)
    - a date of interest
    """

    extent: Extent = param.ClassSelector(class_=Extent, default=Extent(), allow_None=False, constant=True)  # type: ignore

    latitude: float = param.Number(default=0.0, bounds=(-90, 90), allow_None=False)  # type: ignore
    longitude: float = param.Number(default=0.0, bounds=(-180, 180), allow_None=False)  # type: ignore
    date: datetime.datetime = param.Date(default=datetime.datetime(2000, 1, 1), allow_None=False)  # type: ignore

    def __init__(self, **params):
        super().__init__(**params)

        # set extents on lat, lon, date
        self.param.latitude.bounds = (
            self.extent.spatial.latitude_min,
            self.extent.spatial.latitude_max,
        )
        self.param.longitude.bounds = (
            self.extent.spatial.longitude_min,
            self.extent.spatial.longitude_max,
        )
        self.param.date.bounds = (
            self.extent.temporal.t_min,
            self.extent.temporal.t_max,
        )

        # reassign values to trigger validation
        (x, y) = self.extent.spatial.center
        if "latitude" in params:
            self.latitude = params["latitude"]
        else:
            self.latitude = y
        if "longitude" in params:
            self.longitude = params["longitude"]
        else:
            self.longitude = x
        if "date" in params:
            self.date = params["date"]
        else:
            self.date = self.extent.temporal.t_min

    def map_view(self):
        """
        GeoViews plot in Google web mercator projection with a basemap layer.
        Shows the bounding box of the extent, and the (dynamic) point of interest.
        Tap / click on the map to update the point of interest.
        """
        basemap = gv.tile_sources.OSM
        bbox = self.extent.spatial.polygon

        def point(x, y) -> gv.Points:
            """Create a point at the given x, y coordinates."""
            points = gv.Points([(x, y)], kdims=["longitude", "latitude"])
            points.opts(color="red", size=10)
            return points

        point_dmap = hv.DynamicMap(point, streams={"x": self.param.longitude, "y": self.param.latitude})

        tap = streams.Tap(source=point_dmap)

        def on_click(x, y):
            """
            Args:
                x: The x-position of a tap or click in data coordinates.
                y: The y-position of a tap or click in data coordinates.
            """
            try:
                # "transactional" update of both parameters
                self.param.update(longitude=x, latitude=y)
            except ValueError:
                # Ignore clicks outside the bounds
                pass

        tap.add_subscriber(on_click)

        plot = basemap * bbox * point_dmap
        plot.opts(projection=ccrs.GOOGLE_MERCATOR)

        return plot

    def __panel__(self) -> pn.viewable.Viewable:
        return pn.Row(
            pn.Param(
                self,
                parameters=["latitude", "longitude", "date"],
                show_name=False,
                widgets={
                    "latitude": pn.widgets.FloatInput,
                    "longitude": pn.widgets.FloatInput,
                    "date": {
                        "type": pn.widgets.DatetimeSlider,
                        "start": self.extent.temporal.t_min,
                        "end": self.extent.temporal.t_max,
                        "step": 60 * 60,  # 1 hour step
                        "throttled": True,
                    },
                },
            ),
            pn.pane.HoloViews(self.map_view()),
        )
