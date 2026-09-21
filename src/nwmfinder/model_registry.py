"""Registry describing where each supported NWM model variant's files live.

Each :class:`ModelVariant` describes the cadence/lead-time structure of a model
(e.g. short_range, medium_range_mem1, analysis_assim...) and one or more
:class:`SourceTemplate` entries, keyed by an explicit source id (e.g.
``"NOMADS"``, ``"NODD"``, ``"RETRO"``), describing how to build a URL for that
model at a particular source.

Path templates are plain ``str.format`` templates evaluated with keyword
arguments; the specific keys available depend on ``ModelVariant.kind``:

* ``"forecast"`` templates receive: ``model_dir``, ``model_name``,
  ``var_file_suffix``, ``init_yyyymmdd``, ``init_hour``, ``forecast_hour``,
  ``domain``, ``fnum_width``.
* ``"retrospective"`` templates receive: ``forecast_year``, ``forecast_month``,
  ``forecast_day``, ``forecast_hourz``.

Each source may support one or more "products":

* ``"channel_rt"`` (streamflow, a.k.a. CHRTOUT in the retrospective dataset).
* ``"terrain_rt"`` (gridded land-surface fields, a.k.a. GWOUT in the
  retrospective dataset). terrain_rt files are often produced at a coarser
  cadence than channel_rt within the same model--see ``terrain_dt_h``.
* ``"land"`` (gridded land-surface fields, a.k.a. LDASOUT in the retrospective
  dataset). Present for every model variant; follows the same cadence as
  terrain_rt where that product exists, otherwise the channel_rt cadence--see
  ``land_dt_h``.
"""
from __future__ import annotations

from dataclasses import dataclass, field

PRODUCT_CHANNEL_RT = "channel_rt"
PRODUCT_TERRAIN_RT = "terrain_rt"
PRODUCT_LAND = "land"
PRODUCTS = (PRODUCT_CHANNEL_RT, PRODUCT_TERRAIN_RT, PRODUCT_LAND)


@dataclass(frozen=True)
class SourceTemplate:
    """Describes how to build an absolute URL for a model variant at one source."""

    url_base: str
    path_template: str
    terrain_path_template: str | None = None
    land_path_template: str | None = None
    version: str = ""
    ssl_verify: bool = True

    def template_for(self, product: str) -> str:
        if product == PRODUCT_CHANNEL_RT:
            return self.path_template
        if product == PRODUCT_TERRAIN_RT:
            if self.terrain_path_template is None:
                raise ValueError(f"This source has no {PRODUCT_TERRAIN_RT!r} product available.")
            return self.terrain_path_template
        if product == PRODUCT_LAND:
            if self.land_path_template is None:
                raise ValueError(f"This source has no {PRODUCT_LAND!r} product available.")
            return self.land_path_template
        raise ValueError(f"Unknown product {product!r}. Expected one of {PRODUCTS}.")


@dataclass(frozen=True)
class ModelVariant:
    """Describes a specific NWM model configuration's file layout and cadence."""

    model_id: str
    model_dir: str
    model_name: str
    var_file_suffix: str = ""
    # Geographic domain the files cover (e.g. "conus", "hawaii", "alaska", "puertorico").
    domain: str = "conus"
    # Zero-padded width of the encoded forecast_hour/tm number in file names--wider
    # for domains/models whose lead time is encoded at sub-hourly resolution.
    fnum_width: int = 3
    # Cadence/availability parameters (all in hours unless noted).
    hours: int = 240
    run_freq: int = 6
    lag: int = 5
    stride: float = 1
    download_stride: int = 1
    # terrain_rt files commonly use a coarser cadence than channel_rt within the
    # same model (e.g. medium_range terrain_rt is every 3h while channel_rt is hourly).
    terrain_dt_h: int = 1
    # land cadence matches terrain_rt where present, otherwise channel_rt (see module docstring).
    land_dt_h: int = 1
    # 0 = single cycle; N = also return the N cycles preceding the latest one.
    runs: int = 0
    kind: str = "forecast"  # "forecast" or "retrospective"
    sources: dict[str, SourceTemplate] = field(default_factory=dict)

    def source(self, source_id: str) -> SourceTemplate:
        try:
            return self.sources[source_id]
        except KeyError:
            raise KeyError(
                f"Model {self.model_id!r} has no {source_id!r} source. "
                f"Available: {sorted(self.sources)}"
            ) from None


_NOMADS_BASE = "https://nomads.ncep.noaa.gov/pub/data/nccf/com/nwm/v{version}/"
_NODD_BASE = "https://storage.googleapis.com/national-water-model/"
_RETRO_BASE = "https://s3.amazonaws.com/noaa-nwm-retrospective-3-0-pds/CONUS/netcdf/"

# Forward-looking forecast file (f### lead hour). `domain` and `fnum_width` are
# supplied per ModelVariant so one template covers conus/hawaii/alaska/puertorico.
_FORECAST_CHANNEL_RT = (
    "nwm.{init_yyyymmdd}/{model_dir}/nwm.t{init_hour:02d}z."
    "{model_name}.channel_rt{var_file_suffix}.f{forecast_hour:0{fnum_width}d}.{domain}.nc"
)
_FORECAST_TERRAIN_RT = (
    "nwm.{init_yyyymmdd}/{model_dir}/nwm.t{init_hour:02d}z."
    "{model_name}.terrain_rt{var_file_suffix}.f{forecast_hour:0{fnum_width}d}.{domain}.nc"
)
# Backward-looking "time-minus" analysis file (tm## lag hour).
_ANALYSIS_CHANNEL_RT = (
    "nwm.{init_yyyymmdd}/{model_dir}/nwm.t{init_hour:02d}z."
    "{model_name}.channel_rt{var_file_suffix}.tm{forecast_hour:0{fnum_width}d}.{domain}.nc"
)
_ANALYSIS_TERRAIN_RT = (
    "nwm.{init_yyyymmdd}/{model_dir}/nwm.t{init_hour:02d}z."
    "{model_name}.terrain_rt{var_file_suffix}.tm{forecast_hour:0{fnum_width}d}.{domain}.nc"
)
_FORECAST_LAND = (
    "nwm.{init_yyyymmdd}/{model_dir}/nwm.t{init_hour:02d}z."
    "{model_name}.land{var_file_suffix}.f{forecast_hour:0{fnum_width}d}.{domain}.nc"
)
_ANALYSIS_LAND = (
    "nwm.{init_yyyymmdd}/{model_dir}/nwm.t{init_hour:02d}z."
    "{model_name}.land{var_file_suffix}.tm{forecast_hour:0{fnum_width}d}.{domain}.nc"
)
_RETRO_CHRTOUT = (
    "CHRTOUT/{forecast_year:04d}/{forecast_year:04d}{forecast_month:02d}"
    "{forecast_day:02d}{forecast_hourz:02d}00.CHRTOUT_DOMAIN1"
)
_RETRO_GWOUT = (
    "GWOUT/{forecast_year:04d}/{forecast_year:04d}{forecast_month:02d}"
    "{forecast_day:02d}{forecast_hourz:02d}00.GWOUT_DOMAIN1"
)
_RETRO_LDASOUT = (
    "LDASOUT/{forecast_year:04d}/{forecast_year:04d}{forecast_month:02d}"
    "{forecast_day:02d}{forecast_hourz:02d}00.LDASOUT_DOMAIN1"
)


MODEL_REGISTRY: dict[str, ModelVariant] = {
    "short_range": ModelVariant(
        model_id="short_range",
        model_dir="short_range",
        model_name="short_range",
        hours=18,
        run_freq=1,
        lag=1,
        terrain_dt_h=1,
        land_dt_h=1,
        sources={
            "NOMADS": SourceTemplate(_NOMADS_BASE, _FORECAST_CHANNEL_RT, _FORECAST_TERRAIN_RT, _FORECAST_LAND, version="3.1"),
        },
    ),
    "short_range_hawaii": ModelVariant(
        model_id="short_range_hawaii",
        model_dir="short_range_hawaii",
        model_name="short_range",
        domain="hawaii",
        fnum_width=5,
        hours=48,
        run_freq=12,
        lag=3,
        stride=0.25,
        terrain_dt_h=1,
        land_dt_h=1,
        sources={
            "NOMADS": SourceTemplate(_NOMADS_BASE, _FORECAST_CHANNEL_RT, _FORECAST_TERRAIN_RT, _FORECAST_LAND, version="3.1"),
        },
    ),
    "medium_range_mem1": ModelVariant(
        model_id="medium_range_mem1",
        model_dir="medium_range_mem1",
        model_name="medium_range",
        var_file_suffix="_1",
        hours=240,
        run_freq=6,
        lag=5,
        terrain_dt_h=3,
        land_dt_h=3,
        sources={
            "NOMADS": SourceTemplate(_NOMADS_BASE, _FORECAST_CHANNEL_RT, _FORECAST_TERRAIN_RT, _FORECAST_LAND, version="3.1"),
            "NODD": SourceTemplate(_NODD_BASE, _FORECAST_CHANNEL_RT, _FORECAST_TERRAIN_RT, _FORECAST_LAND, version="3.1", ssl_verify=False),
        },
    ),
    "medium_range_blend": ModelVariant(
        model_id="medium_range_blend",
        model_dir="medium_range_blend",
        model_name="medium_range_blend",
        hours=240,
        run_freq=6,
        lag=5,
        terrain_dt_h=3,
        land_dt_h=3,
        sources={
            "NOMADS": SourceTemplate(_NOMADS_BASE, _FORECAST_CHANNEL_RT, _FORECAST_TERRAIN_RT, _FORECAST_LAND, version="3.1"),
            "NODD": SourceTemplate(_NODD_BASE, _FORECAST_CHANNEL_RT, _FORECAST_TERRAIN_RT, _FORECAST_LAND, version="3.1"),
        },
    ),
    "long_range_mem1": ModelVariant(
        model_id="long_range_mem1",
        model_dir="long_range_mem1",
        model_name="long_range",
        var_file_suffix="_1",
        hours=720,
        run_freq=6,
        lag=5,
        stride=6,
        # No terrain_rt product for long_range--land follows the channel_rt cadence instead.
        land_dt_h=6,
        sources={
            "NODD": SourceTemplate(_NODD_BASE, _FORECAST_CHANNEL_RT, land_path_template=_FORECAST_LAND, version="3.1"),
        },
    ),
    "analysis_assim": ModelVariant(
        model_id="analysis_assim",
        model_dir="analysis_assim",
        model_name="analysis_assim",
        hours=3,
        run_freq=1,
        lag=0,
        stride=-1,
        fnum_width=2,
        terrain_dt_h=1,
        land_dt_h=1,
        sources={
            "NOMADS": SourceTemplate(_NOMADS_BASE, _ANALYSIS_CHANNEL_RT, _ANALYSIS_TERRAIN_RT, _ANALYSIS_LAND, version="3.1"),
        },
    ),
    "analysis_assim_tm0": ModelVariant(
        model_id="analysis_assim_tm0",
        model_dir="analysis_assim",
        model_name="analysis_assim",
        hours=1,
        run_freq=1,
        lag=0,
        stride=-1,
        fnum_width=2,
        terrain_dt_h=1,
        land_dt_h=1,
        sources={
            "NOMADS": SourceTemplate(_NOMADS_BASE, _ANALYSIS_CHANNEL_RT, _ANALYSIS_TERRAIN_RT, _ANALYSIS_LAND, version="3.1"),
        },
    ),
    "analysis_assim_tm0_r24": ModelVariant(
        model_id="analysis_assim_tm0_r24",
        model_dir="analysis_assim",
        model_name="analysis_assim",
        hours=1,
        run_freq=1,
        lag=0,
        stride=-1,
        fnum_width=2,
        terrain_dt_h=1,
        land_dt_h=1,
        runs=24,
        sources={
            "NOMADS": SourceTemplate(_NOMADS_BASE, _ANALYSIS_CHANNEL_RT, _ANALYSIS_TERRAIN_RT, _ANALYSIS_LAND, version="3.1"),
        },
    ),
    "analysis_assim_hawaii_tm0_r24": ModelVariant(
        model_id="analysis_assim_hawaii_tm0_r24",
        model_dir="analysis_assim_hawaii",
        model_name="analysis_assim",
        domain="hawaii",
        fnum_width=4,
        hours=1,
        run_freq=1,
        lag=1,
        stride=-0.25,
        terrain_dt_h=1,
        land_dt_h=1,
        runs=24,
        sources={
            "NOMADS": SourceTemplate(_NOMADS_BASE, _ANALYSIS_CHANNEL_RT, _ANALYSIS_TERRAIN_RT, _ANALYSIS_LAND, version="3.1"),
        },
    ),
    "retrospective": ModelVariant(
        model_id="retrospective",
        model_dir="",
        model_name="",
        hours=1,
        run_freq=1,
        lag=0,
        terrain_dt_h=1,
        land_dt_h=1,
        kind="retrospective",
        sources={
            "RETRO": SourceTemplate(_RETRO_BASE, _RETRO_CHRTOUT, _RETRO_GWOUT, _RETRO_LDASOUT, version="3.0"),
        },
    ),
}
