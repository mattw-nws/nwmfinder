# nwmfinder

**Description**: `nwmfinder` is a small, standard-library-only Python package for discovering,
checking the availability of, and downloading [National Water Model (NWM)](https://water.noaa.gov/about/nwm)
data files. It knows how to locate `channel_rt` (streamflow), `terrain_rt`, and `land` product
files across NWM's various forecast configurations (short range, medium range, analysis & assimilation,
long range) and the retrospective archive, from NOMADS, NOAA's Open Data Dissemination (NODD)
program (Google Cloud Storage), or the NWM retrospective S3 archive.

  - **Technology stack**: Python 3.10+. The `nwmfinder` package has no dependencies outside the
    Python standard library at runtime.
  - **Status**: Early development (0.0.1).

## Dependencies

`nwmfinder` itself requires only Python 3.10 or later--no third-party runtime dependencies.

Running the test suite requires [pytest](https://pytest.org); building the documentation requires
[Sphinx](https://www.sphinx-doc.org). Both are available as optional extras (see below).

## Installation

From the root of a checkout of this repository:

```bash
pip install .

# Or, for local development (editable install):
pip install -e .[dev]
```

## Usage

```python
from nwmfinder import NwmFinder, Downloader

finder = NwmFinder()

# Locate the latest available short_range cycle on NOMADS.
cycles = finder.locate("short_range", "NOMADS")
cycle = cycles[0]
print(cycle.init_time, len(cycle.files), "files")

# Download all of that cycle's channel_rt files into a local cache.
downloader = Downloader(cache_dir="./cache")
results = downloader.download_references(cycle.files)
for result in results:
    print(result.url, "->", result.path if result.success else result.error)
```

`nwmfinder` can also locate data covering an arbitrary historical date range, automatically
choosing between NOMADS, NODD, and the retrospective archive the same way a human operator would:

```python
from datetime import datetime, timezone
from nwmfinder import NwmFinder

finder = NwmFinder()
cycles = finder.locate_range(
    datetime(2023, 6, 1, 0, tzinfo=timezone.utc),
    datetime(2023, 6, 1, 6, tzinfo=timezone.utc),
)
```

See the [full documentation](https://mattw-nws.github.io/nwmfinder/) for more detail, including
the `terrain_rt`/`land` products and explicit source/model selection.

> **Note**: This repository also contains `downloader.py` and `source_manager.py`, two earlier,
> project-specific prototypes that `nwmfinder` was extracted and generalized from. They are kept
> for reference but are not part of the `nwmfinder` package, its documentation, or its tests.

## Configuration

`nwmfinder` is configured entirely through constructor/method arguments--there is no external
configuration file. See `NwmFinder` and `Downloader` in the [API reference](https://mattw-nws.github.io/nwmfinder/)
for the full set of options (cache directory, `max_workers`, retry counts, explicit source/model
selection, etc).

## How to test the software

```bash
pip install -e .[dev]
pytest -q
```

Tests run automatically on every push and pull request via the "Tests" GitHub Actions workflow.

## Documentation

Documentation is built with Sphinx from the `doc/` directory and published to GitHub Pages via
the "Docs" GitHub Actions workflow. To build it locally:

```bash
pip install -e .[docs]
sphinx-build -b html doc doc/_build/html
```

## Known issues

`nwmfinder` is early-stage software; its model registry covers the NWM configurations exercised
by its predecessor scripts, but may not yet cover every NWM domain/product combination.

## Getting help

If you have questions, concerns, bug reports, etc., please file an issue in this repository's
issue tracker.

## Getting involved

Contributions are welcome, particularly around expanding model registry coverage and hardening
the discovery/download heuristics. See [CONTRIBUTING](CONTRIBUTING.md) for details.

----

## Open source licensing info

1. [TERMS](TERMS.md)
2. [LICENSE](LICENSE)

----

## Credits and references

1. [National Water Model](https://water.noaa.gov/about/nwm), NOAA/NWS Office of Water Prediction
2. [NOMADS](https://nomads.ncep.noaa.gov/)
3. [NOAA Open Data Dissemination (NODD) Program](https://www.noaa.gov/information-technology/open-data-dissemination)

