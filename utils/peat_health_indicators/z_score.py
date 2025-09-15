import abc
import typing

import holoviews as hv
import pandas as pd
import panel as pn
import param

from .. import utils
from . import annual_climatology, daily_climatology


class BaseVariable(pn.viewable.Viewer):
    """
    Container for a site-level (aggregated) time series variable.

    Transforms the time series to abs(data - optimal_value) if `transform` is True.
    This is useful if the variable is not monotonically correlated with peat health.

    All pandas Series and DataFrames should share a common DatetimeIndex.
    """

    name: str = param.String(allow_None=False)  # type: ignore
    units: str = param.String(allow_None=True, default=None)  # type: ignore

    colour: str = param.String(default="#30a2da", allow_None=False)  # type: ignore

    data: pd.Series = param.Series(allow_None=False, constant=True, doc="Time series")  # type: ignore
    variance: pd.Series = param.Series(allow_None=False, constant=True, doc="Variance of the time series")  # type: ignore

    optimal_value: float = param.Number()  # type: ignore
    transform: bool = param.Boolean(
        allow_None=False, default=False, label="Apply transformation relative to optimal value"
    )  # type: ignore

    time_series: pd.Series = param.Series(allow_None=False, constant=True, doc="Time series, transformed if requested")  # type: ignore
    climatology_bounds: pd.DataFrame = param.DataFrame(allow_None=False, constant=True)  # type: ignore
    z_score: pd.Series = param.Series(allow_None=False, constant=True, doc="Standard anomaly of the time series")  # type: ignore

    @param.depends("transform", "optimal_value", watch=True, on_init=True)
    def transform_time_series(self):
        """
        Computes and sets time_series, climatology_bounds, and z_score.
        If `transform` is True, calculate the absolute difference from `optimal_value`.
        """
        # override this method to provide implementation
        self._transform_time_series()

    @abc.abstractmethod
    def _transform_time_series(self):
        """
        Computes and sets time_series, climatology_bounds, and z_score.
        If `transform` is True, calculate the absolute difference from `optimal_value`.
        """
        raise NotImplementedError

    def widgets(self) -> pn.Param:
        return pn.Param(
            self,
            parameters=["optimal_value", "transform"],
            show_name=False,
            widgets={
                # "colour": pn.widgets.ColorPicker,
                # "optimal_value": {"visible": self.param.transform.rx()},
            },
        )

    def _fix_index_names(self):
        """
        Ensure that all pandas objects have index name "time".
        This is necessary for HoloViews to correctly map the index to a key dimension.
        """
        for pandas_obj in [self.data, self.variance, self.time_series, self.climatology_bounds, self.z_score]:
            if not isinstance(pandas_obj.index, pd.DatetimeIndex):
                raise ValueError("Index must be a DatetimeIndex")
            if pandas_obj.index.name != "time":
                pandas_obj.index.name = "time"

    @property
    def y_label(self):
        if self.units:
            return f"{self.name} ({self.units})"
        else:
            return self.name

    @param.depends("colour", watch=False)
    def original_data_view(self):
        """
        HoloViews plot of the original time series (not transformed relative to the optimal value).
        """
        self._fix_index_names()

        curve = hv.Curve(
            self.data,
            kdims=["time"],
            # vdims=[self.name],
        )
        curve.opts(color=self.colour)

        scatter = hv.Scatter(
            self.data,
            kdims=["time"],
            # vdims=[self.name],
        )
        scatter.opts(color=self.colour, size=4)

        std = self.variance**0.5

        error_bars = hv.ErrorBars(
            (self.data.index, self.data, std),
            kdims=["time"],
            vdims=[self.name, f"{self.name}_std"],
        )

        overlay = error_bars * curve * scatter
        overlay.opts(
            title=f"{self.name} with error bars at 1 standard deviation",
            xlabel="date",
            ylabel=self.y_label,
        )

        return overlay

    @param.depends("colour", "transform", "time_series", "climatology_bounds", watch=False)
    def time_series_view(self):
        """
        Holoviews plot of the time series,
        potentially transformed relative to the optimal value (depending on `transform`).

        Shows the climatology envelope.
        """
        self._fix_index_names()

        if self.transform:
            title = f"{self.name} (relative to optimal) with climatology at 1 standard deviation"
        else:
            title = f"{self.name} with climatology at 1 standard deviation"

        curve = hv.Curve(
            self.time_series,
            kdims=["time"],
        )
        curve.opts(
            framewise=True,  # allow ylims to update
            color=self.colour,
        )

        scatter = hv.Scatter(
            self.time_series,
            kdims=["time"],
        )
        scatter.opts(color=self.colour, size=4)

        area = hv.Area(
            # fill between (X, Y1, Y2)
            (
                self.climatology_bounds.index,
                self.climatology_bounds["lower bound"],
                self.climatology_bounds["upper bound"],
            ),
            kdims=["time"],
            vdims=["lower bound", "upper bound"],
        )
        # this redim prevents axes from automatically linking
        area: hv.Area = area.redim(
            **{
                "lower bound": f"{self.name} lower bound",
                "upper bound": f"{self.name} upper bound",
            }
        )  # type: ignore
        area.opts(color="grey", alpha=0.4)

        overlay = area * curve * scatter
        overlay.opts(
            title=title,
            xlabel="date",
            ylabel=self.y_label,
        )

        return overlay

    @param.depends("colour", "z_score", watch=False)
    def z_score_view(self):
        """
        Holoviews plot of the standard anomaly (z-score) of the time series.
        """
        self._fix_index_names()

        negative_colour = utils.darker(self.colour)
        colour = self.z_score.map(
            lambda z: negative_colour if z < 0 else self.colour
        )

        bars = hv.Bars(
            {"time": self.z_score.index, "z-score": self.z_score.values, "color": colour},
            kdims=["time"],
            vdims=["z-score", "color"],
        )
        # this redim prevents axes from automatically linking
        bars: hv.Bars = bars.redim(
            **{
                "z-score": f"{self.name} z-score",
            }
        )  # type: ignore
        bars.opts(color="color", line_color=None, bar_width=1)
        bars.opts(
            title=f"{self.name} z-score",
            xlabel="date",
            ylabel=self.name,
        )

        return bars

    def __panel__(self) -> pn.Column:
        """
        Panel layout for the Variable.
        """
        # IMPORTANT: plot size and layout must be set consistently twice!
        # 1. on the HoloViews object .opts(responsive=True)
        # 2. on the pn.pane.HoloViews(sizing_mode=...)

        HEIGHT = 300
        MIN_WIDTH = 600

        original_data_view = hv.DynamicMap(self.original_data_view)
        original_data_view.opts(
            height=HEIGHT,
            min_width=MIN_WIDTH,
            responsive=True,
        )

        time_series_view = hv.DynamicMap(self.time_series_view)
        time_series_view.opts(
            height=HEIGHT,
            min_width=MIN_WIDTH,
            responsive=True,
        )

        z_score_view = hv.DynamicMap(self.z_score_view)
        z_score_view.opts(
            height=HEIGHT,
            min_width=MIN_WIDTH,
            responsive=True,
        )

        return pn.Column(
            pn.Row(
                pn.pane.HoloViews(
                    original_data_view,
                    height=HEIGHT,
                    min_width=MIN_WIDTH,
                    sizing_mode="stretch_width",
                )
            ),
            pn.Row(
                pn.pane.HoloViews(
                    time_series_view,
                    height=HEIGHT,
                    min_width=MIN_WIDTH,
                    sizing_mode="stretch_width",
                )
            ),
            pn.Row(
                pn.pane.HoloViews(
                    z_score_view,
                    height=HEIGHT,
                    min_width=MIN_WIDTH,
                    sizing_mode="stretch_width",
                ),
            ),
            width_policy="max",
        )


class DailyVariable(BaseVariable):
    """
    Variable on a daily time series.
    """

    @typing.override
    def _transform_time_series(self):
        """
        Computes and sets time_series, climatology_bounds, and z_score.
        If `transform` is True, calculate the absolute difference from `optimal_value`.
        """
        if self.transform:
            time_series = (self.data - self.optimal_value).abs()
        else:
            time_series = self.data

        # 365-day climatology
        climatology_365 = daily_climatology.get_climatology(time_series, self.variance)
        climatology_bounds = daily_climatology.get_climatology_bounds(time_series.index, climatology_365)  # type: ignore
        z_score = daily_climatology.get_standard_anomaly(time_series, climatology_365)

        with param.edit_constant(self):
            # single transaction update
            self.param.update(
                time_series=time_series,
                climatology_bounds=climatology_bounds,
                z_score=z_score,
            )


class AnnualVariable(BaseVariable):
    """
    Variable on an annual time series.
    """

    @typing.override
    def _transform_time_series(self):
        """
        Computes and sets time_series, climatology_bounds, and z_score.
        If `transform` is True, calculate the absolute difference from `optimal_value`.
        """
        if self.transform:
            time_series = (self.data - self.optimal_value).abs()
        else:
            time_series = self.data

        # annual climatology
        climatology_annual = annual_climatology.get_climatology(time_series, self.variance)
        climatology_bounds = annual_climatology.get_climatology_bounds(time_series.index, climatology_annual)  # type: ignore
        z_score = annual_climatology.get_standard_anomaly(time_series, climatology_annual)

        with param.edit_constant(self):
            # single transaction update
            self.param.update(
                time_series=time_series,
                climatology_bounds=climatology_bounds,
                z_score=z_score,
            )
