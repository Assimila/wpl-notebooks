Notebooks for the WorldPeatland project.

## Prerequisites

- a python environment defined by `environment.yml`
- install nbstripout before committing any notebooks: `nbstripout --install`

update requirements.txt

```bash
conda export --from-history > environment.yml
```

## run the application in development mode

```bash
PYTHONPATH=$(pwd) panel serve app/*.ipynb --index sites --dev
```

## deploy the application

see `deployment/readme.md`
