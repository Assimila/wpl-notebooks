import os
from typing import Annotated

import holoviews as hv
import pandas as pd
import panel as pn
import param
import pydantic

from . import utils
from .site_z_score import ZScore


class InfoModel(pydantic.BaseModel):
    """
    info.json
    """

    name: str
    description: str
    site_id: str
    default_variable_loading_name: str


# constrain variable loading l_v to [-1, 1]
type loading = Annotated[float, pydantic.Field(ge=-1.0, le=1.0)]


class PredefinedVariableLoading(pydantic.BaseModel):
    """
    Encapsulates a single variable loading configuration.
    As recommended by SVD (Singular Value Decomposition),
    or an expert opinion.
    """

    name: str
    description: str
    optimal_values: dict[str, float]
    variable_loadings: dict[str, loading]


class Loading(param.Parameterized):
    loading: float = param.Number(default=0.0, allow_None=False, bounds=(-1.0, 1.0))  # type: ignore


class SiteLevelPHI(pn.viewable.Viewer):
    """
    Container for site-level (aggregated) peat health indicators.

    See `site-indicators.md` for more information about the data that drives this visualization.

    ```bash
    $ tree .
    .
    ├── info.json
    ├── peat_extent.geojson
    ├── time_series.h5
    └── variable_loading
        ├── expert.json
        ├── svd.json
        └── ...
    ```
    """

    # info.json
    name: str = param.String(allow_None=False, constant=True)  # type: ignore
    description: str = param.String(allow_None=False, constant=True)  # type: ignore
    site_id: str = param.String(allow_None=False, constant=True)  # type: ignore

    variables: dict[str, ZScore] = param.Dict(
        allow_None=False,
        constant=True,
        doc="Mapping from variable-id to ZScore instance",
    )  # type: ignore

    variable_loadings: dict[str, Loading] = param.Dict(
        allow_None=False,
        default={},
        constant=True,
        doc="Mapping from variable-id to loading",
    )  # type: ignore

    predefined_variable_loadings: dict[str, PredefinedVariableLoading] = param.Dict(
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
        """
        total_loading = sum(abs(variable_loading.loading) for variable_loading in self.variable_loadings.values())

        self.peat_health_indicator = sum(
            variable_loading.loading * self.variables[var_id].z_score / total_loading
            for var_id, variable_loading in self.variable_loadings.items()
        )  # type: ignore

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
        # TODO: prevent events from firing during this operation

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
    def from_directory(cls, directory: str) -> "SiteLevelPHI":
        if not os.path.isdir(directory):
            raise NotADirectoryError(directory)

        info_file = os.path.join(directory, "info.json")
        with open(info_file) as f:
            info = InfoModel.model_validate_json(f.read())

        extent_file = os.path.join(directory, "peat_extent.geojson")

        timeseries_file = os.path.join(directory, "time_series.h5")
        data_df = pd.read_hdf(timeseries_file, key="data")
        variance_df = pd.read_hdf(timeseries_file, key="variance")

        variables = {}
        colours = utils.colours()
        for variable_id in data_df.columns:
            variables[variable_id] = ZScore(
                name=variable_id,
                colour=next(colours),
                data=data_df[variable_id],
                variance=variance_df[variable_id],
            )

        variable_loading_dir = os.path.join(directory, "variable_loading")
        if not os.path.isdir(variable_loading_dir):
            raise NotADirectoryError(variable_loading_dir)

        variable_loading_files = [
            os.path.join(variable_loading_dir, f) for f in os.listdir(variable_loading_dir) if f.endswith(".json")
        ]

        predefined_variable_loadings = {}
        for variable_loading_file in variable_loading_files:
            with open(variable_loading_file) as f:
                predefined = PredefinedVariableLoading.model_validate_json(f.read())
                predefined_variable_loadings[predefined.name] = predefined

        obj = cls(
            name=info.name,
            description=info.description,
            site_id=info.site_id,
            variables=variables,
            predefined_variable_loadings=predefined_variable_loadings,
        )

        obj.assign_predefined_variable_loadings(info.default_variable_loading_name)

        return obj

    def widgets(self):
        """
        Sliders to control the loading of each variable
        """
        sliders = []
        for variable_id, variable_loading in self.variable_loadings.items():
            slider = pn.widgets.FloatSlider.from_param(
                variable_loading.param.loading,
                step=0.01,
                bar_color=self.variables[variable_id].param.colour.rx(),
                throttled=True,
                name=variable_id,
            )
            # fix for https://github.com/holoviz/panel/issues/7997
            slider.param.value_throttled.constant = False

            sliders.append(slider)
        return pn.Column(*sliders)

    def predefined_variable_loading_selector(self):
        """
        A dropdown list of the names of the predefined variable loadings.
        Along with a button to apply the selected variable loading configuration.
        """
        selector = pn.widgets.Select(
            options=list(self.predefined_variable_loadings.keys()),
            value=None,
        )
        apply_button = pn.widgets.Button(name="Apply this set of predefined variable loadings", button_type="primary")

        def apply_callback(event):
            if selector.value:
                self.assign_predefined_variable_loadings(selector.value)

        apply_button.on_click(apply_callback)

        return pn.Column(selector, apply_button)

    @param.depends("peat_health_indicator", watch=False)
    def phi_view(self):
        """
        Holoviews plot of the peat_health_indicator time series.
        """
        curve = hv.Curve(
            self.peat_health_indicator,
            kdims=["time"],
        )

        scatter = hv.Scatter(
            self.peat_health_indicator,
            kdims=["time"],
        )
        scatter.opts(size=4)

        overlay = curve * scatter
        overlay.opts(
            xlabel="date",
            ylabel="Peat Health Indicator",
        )

        return overlay

    def __panel__(self):
        # IMPORTANT: plot size and layout must be set consistently twice!
        # 1. on the HoloViews object .opts(responsive=True)
        # 2. on the pn.pane.HoloViews(sizing_mode=...)

        variables = [
            pn.Card(
                variable.widgets(),
                variable,
                title=variable.name,
                collapsed=True,
                header_background=variable.param.colour.rx(),
            )
            for variable in self.variables.values()
        ]

        HEIGHT = 400
        MIN_WIDTH = 600

        phi_view = hv.DynamicMap(self.phi_view)
        phi_view.opts(
            height=HEIGHT,
            min_width=MIN_WIDTH,
            responsive=True,
        )

        return pn.Column(
            *variables,
            pn.pane.HoloViews(
                phi_view,
                sizing_mode="stretch_width",
                height=HEIGHT,
                min_width=MIN_WIDTH,
            ),
        )
