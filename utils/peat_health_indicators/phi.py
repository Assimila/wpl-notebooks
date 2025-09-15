import abc
import typing

import cartopy.crs as ccrs
import geoviews as gv
import holoviews as hv
import numpy as np
import pandas as pd
import panel as pn
import param
import xarray as xr
from matplotlib.colors import ListedColormap

from .. import settings, utils
from . import models, z_score


class Loading(param.Parameterized):
    loading: float = param.Number(default=0.0, allow_None=False, bounds=(-1.0, 1.0))  # type: ignore


class BasePHI(pn.viewable.Viewer):
    """
    Container for site-level (aggregated) peat health indicators.

    See `site-indicators.md` for more information about the data that drives this visualization.
    """

    # info.json
    name: str = param.String(allow_None=False, constant=True)  # type: ignore
    description: str = param.String(allow_None=False, constant=True)  # type: ignore
    site_id: str = param.String(allow_None=False, constant=True)  # type: ignore

    peat_extent: xr.DataArray = param.ClassSelector(
        class_=xr.DataArray, label="Peat extent pixel mask", allow_None=False, constant=True
    )  # type: ignore

    variables: dict[str, z_score.BaseVariable] = param.Dict(
        allow_None=False,
        constant=True,
        doc="Mapping from variable-id to Variable instance",
    )  # type: ignore

    variable_loadings: dict[str, Loading] = param.Dict(
        allow_None=False,
        default={},
        constant=True,
        doc="Mapping from variable-id to loading",
    )  # type: ignore

    predefined_variable_loadings: dict[str, models.PredefinedVariableLoading] = param.Dict(
        allow_None=False,
        constant=True,
        doc="Mapping from name to PredefinedVariableLoading instance",
    )  # type: ignore

    peat_health_indicator: pd.Series = param.Series(
        allow_None=False,
        doc="Time series of site-level peat health indicator",
    )  # type: ignore

    def __init__(self, **params):
        super().__init__(**params)

        # check that variable ids (dict keys) match up
        vars = list(self.variables.keys())
        with param.edit_constant(self):
            for key in self.variable_loadings:
                if key not in vars:
                    del self.variable_loadings[key]
            for key in vars:
                if key not in self.variable_loadings:
                    self.variable_loadings[key] = Loading()

        self.update_peat_health_indicator()

        self._setup_hooks()

    # @param.depends on self.variables.values() and self.variable_loadings.values()
    def update_peat_health_indicator(self):
        """
        Calculate the peat health indicator time series based on the variable loadings.

        Updates self.peat_health_indicator.

        A loading of zero means that the variable should be excluded, thereby avoiding any problems with NaNs.
        """
        # tolerance to consider a loading == zero
        # note SLIDER_STEP = 0.05
        EPSILON = 0.001

        # filter out variables with zero loading
        variable_loadings: dict[str, Loading] = {
            variable_id: variable_loading
            for variable_id, variable_loading in self.variable_loadings.items()
            if abs(variable_loading.loading) > EPSILON
        }

        if len(variable_loadings) == 0:
            # all variable loadings are zero!
            index = self.variables[next(iter(self.variables))].data.index
            series = pd.Series(np.nan, index=index)
            series.index.name = "time"  # for holoviews kdims
            self.peat_health_indicator = series
            return

        total_loading = sum(abs(variable_loading.loading) for variable_loading in variable_loadings.values())

        series: pd.Series = sum(
            variable_loading.loading * self.variables[variable_id].z_score
            for variable_id, variable_loading in variable_loadings.items()
        )  # type: ignore
        series = series / total_loading
        series.index.name = "time"  # for holoviews kdims

        self.peat_health_indicator = series

    def _update_phi(self, *events: param.parameterized.Event):
        """
        An event handler for use with `param.watch` to update the peat health indicator
        """
        self.update_peat_health_indicator()

    def _setup_hooks(self):
        """
        Set up watchers to update the peat health indicator when variables (z-scores) or variable loadings change.
        """
        for variable in self.variables.values():
            variable.param.watch(self._update_phi, "z_score")

        for variable_loading in self.variable_loadings.values():
            variable_loading.param.watch(self._update_phi, "loading")

    def assign_predefined_variable_loadings(self, variable_loading_name: str):
        """
        Assign a pre-defined set of variable loadings by name.

        This is a no-op if `variable_loading_name` is not found in `self.predefined_variable_loadings`.
        """
        # TODO: prevent events from firing during this operation?

        try:
            predefined = self.predefined_variable_loadings[variable_loading_name]
        except KeyError:
            return  # no-op if not found

        variable_ids = list(self.variables.keys())
        for variable_id in variable_ids:
            # optimal_values
            if variable_id in predefined.optimal_values:
                optimal_value = predefined.optimal_values[variable_id]
                # "transactional" update of both parameters
                self.variables[variable_id].param.update(optimal_value=optimal_value, transform=True)
            else:
                self.variables[variable_id].transform = False

            # variable_loadings
            if variable_id in predefined.variable_loadings:
                loading_value = predefined.variable_loadings[variable_id]
                self.variable_loadings[variable_id].loading = loading_value
            else:
                self.variable_loadings[variable_id].loading = 0.0

    @classmethod
    @abc.abstractmethod
    def from_directory(cls, directory: str) -> typing.Self:
        raise NotImplementedError

    def loading_sliders(self):
        """
        Sliders to control the loading of each variable
        """
        SLIDER_STEP = 0.05
        sliders = []
        for variable_id, variable_loading in self.variable_loadings.items():
            slider = pn.widgets.FloatSlider.from_param(
                variable_loading.param.loading,
                step=SLIDER_STEP,
                bar_color=self.variables[variable_id].param.colour.rx(),
                throttled=True,
                name=variable_id,
            )
            sliders.append(slider)
        return pn.Column(*sliders)

    def predefined_variable_loading_selector(self):
        """
        A dropdown list of the names of the predefined variable loadings.
        When one is selected, display the description of the selected variable loading configuration.
        A button to apply the selected variable loading configuration.
        """

        def get_description(predefined_variable_loading_name: str | None) -> str:
            placeholder = "Select a predefined variable loading"
            if predefined_variable_loading_name is None:
                return placeholder
            try:
                return self.predefined_variable_loadings[predefined_variable_loading_name].description
            except KeyError:
                return placeholder

        selector = pn.widgets.Select(
            options=[None] + list(self.predefined_variable_loadings.keys()),
            value=None,
            name="Predefined variable loadings",
        )
        description = pn.pane.Markdown(param.bind(get_description, selector.param.value))
        apply_button = pn.widgets.Button(name="Apply predefined variable loadings", button_type="primary")

        def apply_callback(event):
            if selector.value:
                self.assign_predefined_variable_loadings(selector.value)

        apply_button.on_click(apply_callback)

        return pn.Column(selector, description, apply_button)

    @param.depends("peat_health_indicator", watch=False)
    def phi_view(self):
        """
        Holoviews plot of the peat_health_indicator time series.
        """

        default_colour = next(utils.colours())
        negative_colour = utils.darker(default_colour)
        colour = self.peat_health_indicator.map(lambda z: negative_colour if z < 0 else default_colour)

        bars = hv.Bars(
            {"time": self.peat_health_indicator.index, "phi": self.peat_health_indicator.values, "color": colour},
            kdims=["time"],
            vdims=["phi", "color"],
        )
        bars.opts(color="color", line_color=None, bar_width=1)
        bars.opts(framewise=True)  # allow ylims to update
        bars.opts(
            xlabel="date",
            ylabel="Peat Health Indicator",
        )

        return bars

    def map(self):
        """
        GeoViews plot in google web mercator projection with a basemap layer.
        Shows the peat_extent pixel mask.
        """
        basemap = gv.tile_sources.EsriImagery

        # mask non-peat with NaN
        peat_extent = self.peat_extent.where(self.peat_extent == 1)

        cmap = ListedColormap([settings.PEAT_COLOUR])

        image = gv.Image(peat_extent, kdims=["x", "y"], crs=ccrs.PlateCarree())
        image.opts(projection=ccrs.GOOGLE_MERCATOR)
        image.opts(alpha=settings.PEAT_ALPHA, cmap=cmap)

        overlay = basemap * image
        overlay.opts(projection=ccrs.GOOGLE_MERCATOR)

        return overlay

    def variable_cards(self):
        """
        One panel Card per variable.
        """
        cards = [
            pn.Card(
                variable.widgets(),
                variable,
                title=variable.name,
                collapsed=True,
                header_background=variable.param.colour.rx(),
            )
            for variable in self.variables.values()
        ]
        return pn.Column(*cards)

    def __panel__(self):
        # IMPORTANT: plot size and layout must be set consistently twice!
        # 1. on the HoloViews object .opts(responsive=True)
        # 2. on the pn.pane.HoloViews(sizing_mode=...)
        HEIGHT = 400
        MIN_WIDTH = 600

        phi_view = hv.DynamicMap(self.phi_view)
        phi_view.opts(
            height=HEIGHT,
            min_width=MIN_WIDTH,
            responsive=True,
        )

        return pn.Column(
            pn.pane.HoloViews(
                phi_view,
                sizing_mode="stretch_width",
                height=HEIGHT,
                min_width=MIN_WIDTH,
            )
        )


class DailyPHI(BasePHI):
    @classmethod
    def from_directory(cls, directory: str) -> typing.Self:
        model = models.SiteLevelPHI.from_directory(directory)

        variables = {}
        colours = utils.colours()
        for variable_id in model.data.columns:
            variables[variable_id] = z_score.DailyVariable(
                name=variable_id,
                units=model.info.units.get(variable_id),
                colour=next(colours),
                data=model.data[variable_id],
                variance=model.variance[variable_id],
            )

        obj = cls(
            name=model.info.name,
            description=model.info.description,
            site_id=model.info.site_id,
            peat_extent=model.peat_extent,
            variables=variables,
            predefined_variable_loadings=model.variable_loadings,
        )

        obj.assign_predefined_variable_loadings(model.info.default_variable_loading_name)

        return obj


class AnnualPHI(BasePHI):
    @classmethod
    def from_directory(cls, directory: str) -> typing.Self:
        model = models.SiteLevelPHI.from_directory(directory)

        variables = {}
        colours = utils.colours()
        for variable_id in model.annual_data.columns:
            variables[variable_id] = z_score.AnnualVariable(
                name=variable_id,
                units=model.info.units.get(variable_id),
                colour=next(colours),
                data=model.annual_data[variable_id],
                variance=model.annual_variance[variable_id],
            )

        obj = cls(
            name=model.info.name,
            description=model.info.description,
            site_id=model.info.site_id,
            peat_extent=model.peat_extent,
            variables=variables,
            predefined_variable_loadings=model.variable_loadings,
        )

        obj.assign_predefined_variable_loadings(model.info.default_variable_loading_name)

        return obj
