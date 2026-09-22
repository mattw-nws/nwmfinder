"""Discovery/availability-checking for NWM model cycles.

Ported and hardened from the original prototype `downloader.py` /
`source_manager.py` logic: given a model variant and a source, either walk
backward from "now" to find the most recent complete cycle (auto mode), or
build URLs for an explicitly-provided init time (explicit mode).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from . import _http
from .exceptions import DataNotFoundError, UnexpectedResponseError
from .model_registry import MODEL_REGISTRY, PRODUCT_CHANNEL_RT, PRODUCT_TERRAIN_RT, PRODUCTS, ModelVariant, SourceTemplate

logger = logging.getLogger(__name__)

# Response codes that mean "not posted yet, keep looking"--NOMADS is known to
# hand back 403 (instead of the more conventional 404) for not-yet-available files.
_NOT_FOUND_CODES = frozenset({403, 404})

# How far back we're willing to walk before giving up on finding a cycle.
_MAX_ROLLBACK = timedelta(days=1)

# NODD's archive only goes back to this date; older non-recent data must come from 
# the RETRO(spective) dataset.
_NODD_CUTOFF = datetime(2023, 9, 20, tzinfo=timezone.utc)


def _default_range_source(t0: datetime) -> str:
    """Pick a source for `t0`."""
    wayback = datetime.now(timezone.utc) - t0
    if wayback < timedelta(hours=40):
        return "NOMADS"
    if t0 > _NODD_CUTOFF:
        return "NODD"
    return "RETRO"


@dataclass(frozen=True)
class FileReference:
    url: str
    init_time: datetime
    valid_time: datetime
    forecast_hour: int


@dataclass(frozen=True)
class Cycle:
    model_id: str
    source_id: str
    init_time: datetime
    files: list[FileReference] = field(default_factory=list)
    product: str = PRODUCT_CHANNEL_RT
    # Last-Modified header seen while probing for this cycle's availability, if any.
    last_modified: str | None = None


def _quantize(dt: datetime, run_freq_hours: int) -> datetime:
    quantum = timedelta(hours=run_freq_hours).total_seconds()
    return datetime.fromtimestamp((dt.timestamp() // quantum) * quantum, tz=timezone.utc)


def _lead_times(hours: int, stride: float) -> list[tuple[timedelta, int]]:
    """Return (offset_from_init, forecast_hour_number) pairs for a full cycle.

    ``forecast_hour_number`` matches the on-disk naming convention: a plain
    integer hour count for whole-hour strides, or a concatenated HHMM-style
    integer (e.g. 15 minutes -> 15, 1h30m -> 130) for fractional strides--
    mirroring the legacy prototype's file-naming scheme.
    """
    if stride < 0:
        start_min = int(60 * hours) + int(60 * stride)
        stop_min = int(60 * stride)
        step_min = int(60 * stride)
    else:
        start_min = int(60 * stride)
        stop_min = int(60 * hours) + int(60 * stride)
        step_min = int(60 * stride)

    minutes = range(start_min, stop_min, step_min)
    result = []
    for m in minutes:
        offset = timedelta(minutes=m)
        if stride % 1 != 0:
            fnum = (100 * (m // 60)) + (m % 60)
        else:
            fnum = m // 60
        result.append((offset, fnum))
    return result


def _probe_forecast_hour(hours: int, stride: float) -> int:
    """Forecast-hour to check for existence as a proxy for "cycle is posted".

    Forward-looking models: the last (longest lead-time) file, since that's the
    last one written for the cycle. Backward-looking ("tm") models: hour 0,
    since that's the first (most current) one written.
    """
    if stride > 0:
        if stride % 1 != 0:
            return int((100*((hours*60)//60))+((hours*60)%60)) # Should work for non-whole-number hours.
        return hours
    return 0


def _with_last_modified(cycle: Cycle, last_modified: str | None) -> Cycle:
    return Cycle(
        model_id=cycle.model_id,
        source_id=cycle.source_id,
        init_time=cycle.init_time,
        files=cycle.files,
        product=cycle.product,
        last_modified=last_modified,
    )


class NwmFinder:
    """Finds/locates NWM data file URLs for a configured model+source."""

    def __init__(self, registry: dict[str, ModelVariant] | None = None, *, max_retries: int = 3, retry_backoff: float = 5.0):
        self._registry = registry if registry is not None else MODEL_REGISTRY
        self._max_retries = max_retries
        self._retry_backoff = retry_backoff

    def variant(self, model_id: str) -> ModelVariant:
        try:
            return self._registry[model_id]
        except KeyError:
            raise KeyError(f"Unknown model id {model_id!r}. Available: {sorted(self._registry)}") from None

    def list_sources(self, model_id: str) -> list[str]:
        return sorted(self.variant(model_id).sources)

    def locate(
        self,
        model_id: str,
        source_id: str,
        *,
        product: str = PRODUCT_CHANNEL_RT,
        init_time: datetime | None = None,
        runs: int | None = None,
    ) -> list[Cycle]:
        """Locate one or more cycles' worth of file URLs.

        ``product`` selects which file kind to locate: ``"channel_rt"``
        (streamflow/CHRTOUT), ``"terrain_rt"`` (gridded terrain fields/GWOUT),
        or ``"land"`` (gridded land-surface fields/LDASOUT)--each of which may
        follow a different cadence within the same model. If ``init_time`` is
        given, it is used directly (explicit selection) and no availability
        probing is performed. Otherwise the most recent complete cycle is
        located by walking backward from now.
        """
        if product not in PRODUCTS:
            raise ValueError(f"Unknown product {product!r}. Expected one of {PRODUCTS}.")

        variant = self.variant(model_id)
        source = variant.source(source_id)
        template = source.template_for(product)

        if variant.kind == "retrospective":
            if init_time is None:
                raise ValueError("Retrospective models require an explicit init_time.")
            return [self._build_retrospective_cycle(variant, source, source_id, product, template, init_time)]

        n_runs = variant.runs if runs is None else runs
        if product == PRODUCT_CHANNEL_RT:
            effective_stride = variant.stride
        elif product == PRODUCT_TERRAIN_RT:
            effective_stride = float(variant.terrain_dt_h)
        else:  # PRODUCT_LAND
            effective_stride = float(variant.land_dt_h)

        last_modified = None
        if init_time is not None:
            latest = _quantize(init_time, variant.run_freq)
        else:
            latest, last_modified = self._find_latest_cycle(variant, source, template, effective_stride)

        cycles: list[Cycle] = []
        cycle_time = latest
        for i in range(max(n_runs, 0) + 1):
            cycle = self._build_forecast_cycle(variant, source, source_id, product, template, effective_stride, cycle_time)
            if i == 0:
                cycle = _with_last_modified(cycle, last_modified)
            cycles.append(cycle)
            cycle_time = cycle_time - timedelta(hours=variant.run_freq)
        cycles.reverse()
        return cycles

    def locate_range(
        self,
        t0: datetime,
        tend: datetime | None = None,
        *,
        product: str = PRODUCT_CHANNEL_RT,
        source: str | None = None,
        model_id: str | None = None,
    ) -> list[Cycle]:
        """Locate the file(s) needed to cover [t0, tend] for `product`.

        If ``source`` isn't given, NOMADS is used for data less than 40h old,
        NODD for older data after the NODD cutover date, and RETRO
        (retrospective) otherwise. ``model_id`` defaults to ``"retrospective"``
        for the RETRO source and ``"medium_range_mem1"`` otherwise, but may be
        overridden explicitly. Returns a list of `Cycle` objects (currently
        always one) whose `files` fully enumerate the range at the product's
        native cadence.
        """
        if product not in PRODUCTS:
            raise ValueError(f"Unknown product {product!r}. Expected one of {PRODUCTS}.")
        if tend is not None and tend < t0:
            raise ValueError("tend must not be before t0.")

        source_id = source if source is not None else _default_range_source(t0)
        if model_id is None:
            model_id = "retrospective" if source_id == "RETRO" else "medium_range_mem1"

        variant = self.variant(model_id)
        src = variant.source(source_id)
        template = src.template_for(product)

        if product == PRODUCT_CHANNEL_RT:
            dt_h = 1
        elif product == PRODUCT_TERRAIN_RT:
            dt_h = variant.terrain_dt_h
        else:  # PRODUCT_LAND
            dt_h = variant.land_dt_h

        if variant.kind == "retrospective":
            cycle = self._locate_range_retrospective(variant, src, source_id, product, template, t0, tend, dt_h)
        else:
            cycle = self._locate_range_forecast(variant, src, source_id, product, template, t0, tend, dt_h)
        return [cycle]

    def _locate_range_forecast(
        self,
        variant: ModelVariant,
        source: SourceTemplate,
        source_id: str,
        product: str,
        template: str,
        t0: datetime,
        tend: datetime | None,
        dt_h: int,
    ) -> Cycle:
        attempt = min(t0, datetime.now(timezone.utc) - timedelta(hours=variant.lag))
        attempt = _quantize(attempt, variant.run_freq)
        start = attempt

        while True:
            t0_forecast_hour = int((t0 - attempt).total_seconds() // 3600)
            t0_forecast_hour = (t0_forecast_hour // dt_h) * dt_h
            url = self._build_url(variant, source, template, attempt, t0_forecast_hour)
            result = self._probe(url, source.ssl_verify)
            if result.status_code == 200:
                break
            if result.status_code not in _NOT_FOUND_CODES:
                raise UnexpectedResponseError(f"Unexpected response code {result.status_code} for {url}")
            if t0 - attempt >= _MAX_ROLLBACK:
                raise DataNotFoundError(
                    f"Rolled back to {attempt.isoformat()} ({_MAX_ROLLBACK} limit) without finding "
                    f"{variant.model_id} data covering {t0.isoformat()}. Last URL tried: {url}"
                )
            attempt = attempt - timedelta(hours=variant.run_freq)

        init_time = attempt

        if tend is not None and variant.hours > 1:
            delta_hours = (tend - t0).total_seconds() / 3600
            if t0_forecast_hour + delta_hours > variant.hours:
                raise ValueError(
                    f"End date {tend.isoformat()} exceeds the data available for model {variant.model_id} "
                    f"when starting at forecast hour {t0_forecast_hour} (init_time {init_time.isoformat()})"
                )

        fnums = [t0_forecast_hour] if tend is None else range(
            t0_forecast_hour, t0_forecast_hour + int((tend - t0).total_seconds() // 3600) + 1, dt_h
        )
        files = [
            FileReference(
                url=self._build_url(variant, source, template, init_time, fnum),
                init_time=init_time,
                valid_time=init_time + timedelta(hours=fnum),
                forecast_hour=fnum,
            )
            for fnum in fnums
        ]
        return Cycle(model_id=variant.model_id, source_id=source_id, init_time=init_time, files=files, product=product)

    def _locate_range_retrospective(
        self,
        variant: ModelVariant,
        source: SourceTemplate,
        source_id: str,
        product: str,
        template: str,
        t0: datetime,
        tend: datetime | None,
        dt_h: int,
    ) -> Cycle:
        anchor = min(t0, datetime.now(timezone.utc) - timedelta(hours=variant.lag))
        anchor = _quantize(anchor, variant.run_freq)

        url = self._build_retrospective_url(source, template, anchor)
        result = self._probe(url, source.ssl_verify)
        if result.status_code != 200:
            raise DataNotFoundError(f"Retrospective data not found (HTTP {result.status_code}): {url}")

        times = [anchor]
        if tend is not None:
            times = []
            current = anchor
            while current <= tend:
                times.append(current)
                current = current + timedelta(hours=dt_h)

        files = [
            FileReference(
                url=self._build_retrospective_url(source, template, t),
                init_time=t,
                valid_time=t,
                forecast_hour=0,
            )
            for t in times
        ]
        return Cycle(model_id=variant.model_id, source_id=source_id, init_time=anchor, files=files, product=product)

    def _find_latest_cycle(self, variant: ModelVariant, source: SourceTemplate, template: str, stride: float) -> tuple[datetime, str | None]:
        attempt = datetime.now(timezone.utc) - timedelta(hours=variant.lag)
        attempt = _quantize(attempt, variant.run_freq)
        probe_hour = _probe_forecast_hour(variant.hours, stride)
        start = attempt

        while True:
            url = self._build_url(variant, source, template, attempt, probe_hour)
            result = self._probe(url, source.ssl_verify)
            if result.status_code == 200:
                return attempt, result.last_modified
            if result.status_code not in _NOT_FOUND_CODES:
                raise UnexpectedResponseError(f"Unexpected response code {result.status_code} for {url}")
            if start - attempt >= _MAX_ROLLBACK:
                raise DataNotFoundError(
                    f"Rolled back to {attempt.isoformat()} ({_MAX_ROLLBACK} limit) without finding "
                    f"{variant.model_id} data. Last URL tried: {url}"
                )
            attempt = attempt - timedelta(hours=variant.run_freq)

    def _probe(self, url: str, ssl_verify: bool) -> _http.HeadResult:
        retries = self._max_retries
        backoff = self._retry_backoff
        result = None
        while retries >= 0:
            result = _http.head(url, ssl_verify=ssl_verify)
            if result.status_code == 200 or result.status_code in _NOT_FOUND_CODES:
                return result
            logger.warning("Unexpected response %s for %s, %d retries left", result.status_code, url, retries)
            retries -= 1
            if retries >= 0:
                import time

                time.sleep(backoff)
                backoff *= 2
        return result

    def _build_url(self, variant: ModelVariant, source: SourceTemplate, template: str, init_time: datetime, forecast_hour: int) -> str:
        path = template.format(
            model_dir=variant.model_dir,
            model_name=variant.model_name,
            var_file_suffix=variant.var_file_suffix,
            init_yyyymmdd=init_time.strftime("%Y%m%d"),
            init_hour=init_time.hour,
            forecast_hour=forecast_hour,
            domain=variant.domain,
            fnum_width=variant.fnum_width,
        )
        return source.url_base.format(version=source.version) + path

    def _build_forecast_cycle(
        self,
        variant: ModelVariant,
        source: SourceTemplate,
        source_id: str,
        product: str,
        template: str,
        stride: float,
        init_time: datetime,
    ) -> Cycle:
        files = []
        for offset, fnum in _lead_times(variant.hours, stride):
            url = self._build_url(variant, source, template, init_time, fnum)
            files.append(FileReference(url=url, init_time=init_time, valid_time=init_time + offset, forecast_hour=fnum))
        files = files[variant.download_stride - 1 :: variant.download_stride]
        return Cycle(model_id=variant.model_id, source_id=source_id, init_time=init_time, files=files, product=product)

    def _build_retrospective_url(self, source: SourceTemplate, template: str, when: datetime) -> str:
        path = template.format(
            forecast_year=when.year,
            forecast_month=when.month,
            forecast_day=when.day,
            forecast_hourz=when.hour,
        )
        return source.url_base.format(version=source.version) + path

    def _build_retrospective_cycle(
        self,
        variant: ModelVariant,
        source: SourceTemplate,
        source_id: str,
        product: str,
        template: str,
        init_time: datetime,
    ) -> Cycle:
        url = self._build_retrospective_url(source, template, init_time)
        file_ref = FileReference(url=url, init_time=init_time, valid_time=init_time, forecast_hour=0)
        return Cycle(model_id=variant.model_id, source_id=source_id, init_time=init_time, files=[file_ref], product=product)
