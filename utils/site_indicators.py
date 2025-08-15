import os
from collections import defaultdict
from typing import Annotated

import cartopy.crs as ccrs
import geoviews as gv
import holoviews as hv
import pandas as pd
import panel as pn
import param
import pydantic
import rioxarray  # noqa: F401
import xarray as xr
from matplotlib.colors import ListedColormap

from . import settings, utils
from .site_z_score import ZScore


class InfoModel(pydantic.BaseModel):
    """
    Encapsulates the info.json file for a site-level peat health indicator.
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
    for a site-level peat health indicator.

    The presence of a key in `optimal_values` indicates that the variable should be transformed
    to the absolute deviation from the specified value.
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

    Instances of the class may be a few MB in size,
    depending on the number of variables and the length of the time series.
    """

    # info.json
    name: str = param.String(allow_None=False, constant=True)  # type: ignore
    description: str = param.String(allow_None=False, constant=True)  # type: ignore
    site_id: str = param.String(allow_None=False, constant=True)  # type: ignore

    peat_extent: xr.DataArray = param.ClassSelector(
        class_=xr.DataArray, label="Peat extent pixel mask", allow_None=False, constant=True
    )  # type: ignore

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

        series: pd.Series = sum(
            variable_loading.loading * self.variables[var_id].z_score / total_loading
            for var_id, variable_loading in self.variable_loadings.items()
        )  # type: ignore
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
    def from_directory(cls, directory: str) -> "SiteLevelPHI":
        """
        Create a SiteLevelPHI instance from a directory containing the required files.

        ```bash
        $ tree .
        .
        ├── info.json
        ├── peat_extent.tiff
        ├── time_series.h5
        └── variable_loading
            ├── expert.json
            ├── svd.json
            └── ...
        ```
        """
        if not os.path.isdir(directory):
            raise NotADirectoryError(directory)

        info_file = os.path.join(directory, "info.json")
        with open(info_file) as f:
            info = InfoModel.model_validate_json(f.read())

        extent_file = os.path.join(directory, "peat_extent.tiff")
        da = xr.open_dataarray(
            extent_file,
            engine="rasterio",
            default_name="peat_extent",
        )
        da = da.squeeze("band", drop=True)
        # check crs is EPSG:4326
        if da.rio.crs.to_epsg() != 4326:
            raise ValueError(f"Expected EPSG:4326 CRS for peat extent, got {da.rio.crs}")

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
            peat_extent=da,
            variables=variables,
            predefined_variable_loadings=predefined_variable_loadings,
        )

        obj.assign_predefined_variable_loadings(info.default_variable_loading_name)

        return obj

    def loading_sliders(self):
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
        overlay.opts(framewise=True)  # allow ylims to update

        return overlay

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


@pn.cache
def all_site_level_peat_health_indicators() -> dict[str, dict[str, str]]:
    """
    Search `SITE_LEVEL_PHI_DIR` for site-level peat health indicators.

    Returns: mapping from site-id -> extent name -> subdirectory.
    """
    if not os.path.isdir(settings.SITE_LEVEL_PHI_DIR):
        raise NotADirectoryError(settings.SITE_LEVEL_PHI_DIR)

    ret = defaultdict(dict)

    for item in os.listdir(settings.SITE_LEVEL_PHI_DIR):
        item_path = os.path.join(settings.SITE_LEVEL_PHI_DIR, item)
        if not os.path.isdir(item_path):
            continue
        subdir = item_path
        info_file = os.path.join(subdir, "info.json")
        if not os.path.isfile(info_file):
            continue
        with open(info_file, "r") as f:
            info = InfoModel.model_validate_json(f.read())
        ret[info.site_id][info.name] = subdir

    return ret


# deepcopy because mutable objects are cached
@utils.deepcopy
@pn.cache
def get_phi(site_id: str, extent_name: str) -> SiteLevelPHI | None:
    """
    Get a SiteLevelPHI instance for a given site_id and name.
    """
    phis = all_site_level_peat_health_indicators()
    try:
        directory = phis[site_id][extent_name]
    except KeyError:
        return None
    return SiteLevelPHI.from_directory(directory)
