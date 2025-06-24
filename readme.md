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

## run jupyter

```bash
PYTHONPATH=$(pwd) jupyter notebook
```

## run the dashboard in development mode

```bash
PYTHONPATH=$(pwd) panel serve app/*.ipynb --index sites --dev
```
