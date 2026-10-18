# LMIA Watch

Public records of Labour Market Impact Assessment (LMIA) activity in Canada: which
employers are applying to hire temporary foreign workers, where, when, and which
applications were approved or refused. Every row links to the government record it
came from. The site rebuilds itself once a day, at midnight UTC, from the
sources; that scheduled run is the only way anything on it changes.

## Layout
```
pipeline/   Python: scrape, load, merge, indicators, export (owns data/lmia.sqlite)
site/       Cloudflare Worker: pages + JSON API over the pipeline's static JSON
pipeline/schema.sql   the one schema both halves use
data/       raw downloads and outputs (git-ignored)
site/design/wireframes/   the page structure the site implements
.github/workflows/nightly.yml   the one scheduled run that refreshes data and deploys
```

The site runs on free tiers by design: the data ships as static assets with
the Worker, the browser filters the search and map pages, a database holds
only what visitors submit, and object storage holds the downloads.

## Quick start
```
cd pipeline && pip install -e .[dev] && pytest
python -m lmia_pipeline run --limit 1 --detail-budget 2 --db ../data/lmia.sqlite

cd ../site && npm install && npm run db:local && npm run data:local && npm run dev
```

See CLAUDE.md for the rules that matter (operator anonymity, crawl politeness,
exclusions, copy).

## Sources and licences
The ESDC positive and negative LMIA employer lists are published on open.canada.ca
under the Open Government Licence, Canada. Job Bank content is Government of Canada
material reproduced with attribution. The IRCC list of employers found non-compliant
is published on canada.ca. Derived files from this project carry the Open
Government Licence, Canada.
