import panel as pn

from . import settings

THEME_BLUE = "#4788ab"


class MyVanillaTemplate(pn.template.VanillaTemplate):
    """
    A small override to control the header.
    
    The class `BasicTemplate` has parameters `site` and `title`.

    `panel/template/vanilla/vanilla.html` uses `site_title` and `app_title` for the header.
    `site_title` is a link to `site_url`.
    `app_title` is a link back to current page.

    By default `site` -> `site_title` and `title` -> `app_title`.
    """

    def _update_vars(self, *args) -> None:
        super()._update_vars(*args)
        # set title -> site_title to get a link to site_url
        self._render_variables['app_title'] = None
        self._render_variables['site_title'] = self.site or self.title


def get_template(main, sidebar=None) -> pn.template.base.BasicTemplate:
    """
    Returns a Panel template from VanillaTemplate
    """
    # https://panel.holoviz.org/reference/templates/Vanilla.html
    return MyVanillaTemplate(
        main=main,
        main_max_width="1200px",
        sidebar=sidebar,
        collapsed_sidebar=sidebar is None,
        sidebar_width=settings.SIDEBAR_WIDTH,
        # logo="https://www.worldpeatland.org/wp-content/uploads/2024/01/cropped-WorldPeatland_Icon_512pxSq-1-192x192.png",
        # logo="https://www.worldpeatland.org/wp-content/uploads/2024/01/WorldPeatland_Logo_RGB_400px.png",
        title="WorldPeatland Dashboard",  # default is "Panel Application"
        header_background=THEME_BLUE,
        header_color="white",
        favicon="static/favicon-96x96.png",
    )
