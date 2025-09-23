# WorldPeatland Notebooks

This repository contains the implementation of a number of components of the [WorldPeatland](https://www.worldpeatland.org/) project.

1\. A [Panel](https://panel.holoviz.org/) application in the `app/` directory.
This is the project [dashboard interface](https://dashboard.worldpeatland.org/).
Deployment instructions are in the `deployment/` directory.
A user guide for the dashboard is provided in `dashboard-user-guide.md`.

2\. A library of reusable utility functions and GUI components in the `utils/` directory.

3\. A number of example Jupyter notebooks in the `notebooks/` directory.

4\. The implementation of the peat monitoring toolbox in the `stats/` directory.
See also `site-indicators.md` for more information.

## Prerequisites

- a python environment defined by `environment.yml`
- `conda env create -f environment.yml`
- install nbstripout before committing any notebooks: `nbstripout --install`

## Environment variables

`SITE_LEVEL_PHI_DIR` should be an absolute path to a directory where data for the site-level peat health indicators is stored.
This directory should contain one subdirectory per peat extent map, e.g. degero-extent-1, degero-extent-2, etc.
See `site-indicators.md` for more information.

## run jupyter

```bash
PYTHONPATH=$(pwd) jupyter notebook
```

## run the dashboard in development mode

```bash
export SITE_LEVEL_PHI_DIR=<path to phi data directory>
PYTHONPATH=$(pwd) panel serve app/*.ipynb --index sites --dev
```

## convert the dashboard user guide to pdf

```bash
docker run --rm -it -v "$(pwd):/data" jakobkmar/pandoc-all-in-one --include-in-header=dashboard-user-guide/header.tex dashboard-user-guide.md -o dashboard-user-guide.pdf
```
