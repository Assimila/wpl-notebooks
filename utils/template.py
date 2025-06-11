import panel as pn

from . import settings


def get_template(main, sidebar=None) -> pn.template.base.BasicTemplate:
    """
    Returns a Panel template from VanillaTemplate
    """
    # https://panel.holoviz.org/reference/templates/Vanilla.html
    return pn.template.VanillaTemplate(
        main=main,
        main_max_width="1200px",
        sidebar=sidebar,
        collapsed_sidebar=sidebar is None,
        sidebar_width=settings.SIDEBAR_WIDTH,
        # logo="https://www.worldpeatland.org/wp-content/uploads/2024/01/cropped-WorldPeatland_Icon_512pxSq-1-192x192.png",
        # logo="https://www.worldpeatland.org/wp-content/uploads/2024/01/WorldPeatland_Logo_RGB_400px.png",
        site="WorldPeatland Dashboard",
        site_url="/",
        title="",  # default is "Panel Application"
    )
