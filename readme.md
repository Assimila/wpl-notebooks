Notebooks for the WorldPeatland project.

## Prerequisites

- a python environment defined by `environment.yml`
- install nbstripout before committing any notebooks: `nbstripout --install`

update requirements.txt

```bash
conda export --from-history > environment.yml
```

## serve application

```bash
panel serve sites.ipynb collections.ipynb data.ipynb indicators.ipynb --index sites --dev --show
```
