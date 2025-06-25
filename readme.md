# WorldPeatland Notebooks

This repository contains Jupyter notebooks for the WorldPeatland project in the `notebooks/` directory.

It also contains a [Panel](https://panel.holoviz.org/) application in the `app/` directory,
which serves as the dashboard for the project.
Deployment instructions are in the `deployment/` directory.

The `utils/` directory contains utility functions used by the notebooks and the app.

## Prerequisites

- a python environment defined by `environment.yml`
- `conda env create -f environment.yml`
- install nbstripout before committing any notebooks: `nbstripout --install`

update requirements.txt

```bash
conda export --from-history > environment.yml
```

## Environment variables

`SITE_LEVEL_PHI_DIR` should be an absolute path to a directory where data for the site-level peat health indicators is stored.
This directory should contain one subdirectory per peat extent map, e.g. degero-extent-1, degero-extent-2, etc.
See `site-indicators.md` for more information.

TODO: add this to the deployment instructions.

## run jupyter

```bash
PYTHONPATH=$(pwd) jupyter notebook
```

## run the dashboard in development mode

```bash
PYTHONPATH=$(pwd) panel serve app/*.ipynb --index sites --dev
```
