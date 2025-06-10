"""
Defines panel Cards for displaying various components
"""

import panel as pn
import pystac

from . import utils


def root(root: pystac.Catalog, collapsed: bool = False) -> pn.Card:
    """
    Render the root STAC catalog as a Panel card
    """
    objects: list = [pn.pane.Markdown(root.description)]

    return pn.Card(
        collapsed=collapsed,
        collapsible=True,
        title=root.title,
        hide_header=False,
        objects=objects,
        sizing_mode="stretch_width",
    )


def site(site: pystac.Catalog, with_links: bool = False) -> pn.Card:
    """
    Render a site STAC catalog as a Panel card

    Arguments:
        site:
        with_links: If True, adds cross-links to other pages
    """
    objects: list = [pn.pane.Markdown(site.description)]

    if with_links:
        # redirect to the collections page, to choose a collection for the site
        collections_url = utils.get_url("collections", {"site-id": site.id})
        indicators_url = utils.get_url("indicators", {"site-id": site.id})

        objects.append(
            pn.pane.Markdown(
                f"🔗 [Explore the data]({collections_url}) or 🔗 [Explore the peat health indicators]({indicators_url})"
            )
        )

    biome = utils.get_biome(site)
    colour = utils.get_biome_colour(biome)

    return pn.Card(
        collapsed=True,
        collapsible=True,
        title=site.title,
        hide_header=False,
        objects=objects,
        header_background=colour,
        sizing_mode="stretch_width",
    )
