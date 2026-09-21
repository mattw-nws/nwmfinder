from datetime import datetime, timedelta, timezone

from nwmfinder.finder import _lead_times, _probe_forecast_hour, NwmFinder
from nwmfinder.model_registry import MODEL_REGISTRY


def test_lead_times_forward_whole_hours():
    pairs = _lead_times(hours=18, stride=1)
    fnums = [f for _, f in pairs]
    assert fnums == list(range(1, 19))


def test_lead_times_backward_whole_hours():
    pairs = _lead_times(hours=3, stride=-1)
    fnums = [f for _, f in pairs]
    assert fnums == [2, 1, 0]


def test_lead_times_forward_fractional():
    pairs = _lead_times(hours=1, stride=0.25)
    fnums = [f for _, f in pairs]
    assert fnums == [15, 30, 45, 100]


def test_lead_times_backward_fractional():
    pairs = _lead_times(hours=1, stride=-0.25)
    fnums = [f for _, f in pairs]
    assert fnums == [45, 30, 15, 0]


def test_probe_forecast_hour():
    assert _probe_forecast_hour(hours=18, stride=1) == 18
    assert _probe_forecast_hour(hours=3, stride=-1) == 0


def test_locate_with_explicit_init_time_builds_urls_without_network():
    finder = NwmFinder()
    init_time = datetime(2026, 9, 20, 12, tzinfo=timezone.utc)
    cycles = finder.locate("short_range", "NOMADS", init_time=init_time)
    assert len(cycles) == 1
    cycle = cycles[0]
    assert cycle.init_time == init_time
    assert len(cycle.files) == 18
    assert cycle.files[0].url.endswith("nwm.t12z.short_range.channel_rt.f001.conus.nc")
    assert cycle.files[0].url.startswith("https://nomads.ncep.noaa.gov/pub/data/nccf/com/nwm/v3.1/")


def test_locate_medium_range_nodd_source():
    finder = NwmFinder()
    init_time = datetime(2026, 9, 20, 0, tzinfo=timezone.utc)
    cycles = finder.locate("medium_range_mem1", "NODD", init_time=init_time)
    assert cycles[0].files[0].url.startswith("https://storage.googleapis.com/national-water-model/")
    assert "medium_range_mem1" in cycles[0].files[0].url


def test_find_latest_cycle_treats_403_as_not_found(monkeypatch):
    from nwmfinder import _http

    calls = {"n": 0}

    def fake_head(url, *, ssl_verify=True, timeout=None):
        calls["n"] += 1
        # First two attempts "not found" (one 404, one 403), third succeeds.
        if calls["n"] < 3:
            code = 404 if calls["n"] == 1 else 403
            return _http.HeadResult(status_code=code, content_length=None, accept_ranges=False, last_modified=None)
        return _http.HeadResult(status_code=200, content_length=123, accept_ranges=False, last_modified=None)

    monkeypatch.setattr(_http, "head", fake_head)

    finder = NwmFinder()
    cycles = finder.locate("short_range", "NOMADS")
    assert len(cycles) == 1
    assert calls["n"] == 3


def test_find_latest_cycle_raises_when_never_found(monkeypatch):
    from nwmfinder import _http
    from nwmfinder.exceptions import DataNotFoundError

    def fake_head(url, *, ssl_verify=True, timeout=None):
        return _http.HeadResult(status_code=404, content_length=None, accept_ranges=False, last_modified=None)

    monkeypatch.setattr(_http, "head", fake_head)

    finder = NwmFinder()
    import pytest

    with pytest.raises(DataNotFoundError):
        finder.locate("short_range", "NOMADS")


def test_all_registered_models_have_at_least_one_source():
    for model_id, variant in MODEL_REGISTRY.items():
        assert variant.sources, f"{model_id} has no sources configured"


def test_locate_terrain_uses_terrain_cadence_and_path():
    finder = NwmFinder()
    init_time = datetime(2026, 9, 20, 0, tzinfo=timezone.utc)
    cycles = finder.locate("medium_range_mem1", "NOMADS", product="terrain_rt", init_time=init_time)
    cycle = cycles[0]
    assert cycle.product == "terrain_rt"
    # terrain_dt_h=3 for medium_range_mem1, so only every 3rd forecast hour appears.
    assert [f.forecast_hour for f in cycle.files][:3] == [3, 6, 9]
    assert cycle.files[0].url.endswith("nwm.t00z.medium_range.terrain_rt_1.f003.conus.nc")


def test_locate_channel_rt_still_hourly_for_same_model():
    finder = NwmFinder()
    init_time = datetime(2026, 9, 20, 0, tzinfo=timezone.utc)
    cycles = finder.locate("medium_range_mem1", "NOMADS", init_time=init_time)
    assert [f.forecast_hour for f in cycles[0].files][:3] == [1, 2, 3]


def test_locate_retrospective_terrain_uses_gwout_template():
    finder = NwmFinder()
    init_time = datetime(2020, 1, 1, 6, tzinfo=timezone.utc)
    cycles = finder.locate("retrospective", "RETRO", product="terrain_rt", init_time=init_time)
    assert "GWOUT" in cycles[0].files[0].url
    assert cycles[0].files[0].url.endswith("2020010106" + "00.GWOUT_DOMAIN1")


def test_locate_terrain_raises_when_model_has_no_terrain_product():
    finder = NwmFinder()
    init_time = datetime(2026, 9, 20, 0, tzinfo=timezone.utc)
    import pytest

    with pytest.raises(ValueError):
        finder.locate("long_range_mem1", "NODD", product="terrain_rt", init_time=init_time)


def test_locate_rejects_unknown_product():
    finder = NwmFinder()
    import pytest

    with pytest.raises(ValueError):
        finder.locate("short_range", "NOMADS", product="bogus", init_time=datetime(2026, 9, 20, tzinfo=timezone.utc))


def test_locate_land_matches_terrain_cadence_when_present():
    finder = NwmFinder()
    init_time = datetime(2026, 9, 20, 0, tzinfo=timezone.utc)
    cycles = finder.locate("medium_range_mem1", "NOMADS", product="land", init_time=init_time)
    cycle = cycles[0]
    assert cycle.product == "land"
    # land_dt_h=3 for medium_range_mem1, matching its terrain_rt cadence.
    assert [f.forecast_hour for f in cycle.files][:3] == [3, 6, 9]
    assert cycle.files[0].url.endswith("nwm.t00z.medium_range.land_1.f003.conus.nc")


def test_locate_land_falls_back_to_channel_rt_cadence_when_no_terrain():
    finder = NwmFinder()
    init_time = datetime(2026, 9, 20, 0, tzinfo=timezone.utc)
    cycles = finder.locate("long_range_mem1", "NODD", product="land", init_time=init_time)
    # long_range has no terrain_rt product, so land follows its channel_rt stride of 6h.
    assert [f.forecast_hour for f in cycles[0].files][:2] == [6, 12]


def test_locate_retrospective_land_uses_ldasout_template():
    finder = NwmFinder()
    init_time = datetime(2020, 1, 1, 6, tzinfo=timezone.utc)
    cycles = finder.locate("retrospective", "RETRO", product="land", init_time=init_time)
    assert "LDASOUT" in cycles[0].files[0].url
    assert cycles[0].files[0].url.endswith("202001010600.LDASOUT_DOMAIN1")


def test_every_registered_model_supports_land_product():
    finder = NwmFinder()
    for model_id, variant in MODEL_REGISTRY.items():
        for source_id in variant.sources:
            variant.source(source_id).template_for("land")  # should not raise


def test_locate_range_forecast_single_file(monkeypatch):
    from nwmfinder import _http

    monkeypatch.setattr(_http, "head", lambda url, **kw: _http.HeadResult(200, None, False, None))

    finder = NwmFinder()
    t0 = datetime(2026, 9, 1, 3, tzinfo=timezone.utc)
    cycle = finder.locate_range(t0, source="NOMADS", model_id="medium_range_mem1")[0]

    assert cycle.model_id == "medium_range_mem1"
    assert cycle.source_id == "NOMADS"
    assert cycle.init_time == datetime(2026, 9, 1, 0, tzinfo=timezone.utc)
    assert len(cycle.files) == 1
    assert cycle.files[0].forecast_hour == 3
    assert cycle.files[0].url.endswith("f003.conus.nc")


def test_locate_range_forecast_enumerates_tend(monkeypatch):
    from nwmfinder import _http

    monkeypatch.setattr(_http, "head", lambda url, **kw: _http.HeadResult(200, None, False, None))

    finder = NwmFinder()
    t0 = datetime(2026, 9, 1, 3, tzinfo=timezone.utc)
    tend = t0 + timedelta(hours=5)
    cycle = finder.locate_range(t0, tend, source="NOMADS", model_id="medium_range_mem1")[0]

    assert [f.forecast_hour for f in cycle.files] == [3, 4, 5, 6, 7, 8]


def test_locate_range_raises_when_tend_exceeds_model_hours(monkeypatch):
    from nwmfinder import _http
    import pytest

    monkeypatch.setattr(_http, "head", lambda url, **kw: _http.HeadResult(200, None, False, None))

    finder = NwmFinder()
    t0 = datetime(2026, 9, 1, 3, tzinfo=timezone.utc)
    tend = t0 + timedelta(hours=100)
    with pytest.raises(ValueError):
        finder.locate_range(t0, tend, source="NOMADS", model_id="short_range")


def test_locate_range_rolls_back_and_raises_when_never_found(monkeypatch):
    from nwmfinder import _http
    from nwmfinder.exceptions import DataNotFoundError
    import pytest

    monkeypatch.setattr(_http, "head", lambda url, **kw: _http.HeadResult(404, None, False, None))

    finder = NwmFinder()
    t0 = datetime(2026, 9, 1, 3, tzinfo=timezone.utc)
    with pytest.raises(DataNotFoundError):
        finder.locate_range(t0, source="NOMADS", model_id="medium_range_mem1")


def test_locate_range_defaults_to_retrospective_for_old_dates(monkeypatch):
    from nwmfinder import _http

    monkeypatch.setattr(_http, "head", lambda url, **kw: _http.HeadResult(200, None, False, None))

    finder = NwmFinder()
    t0 = datetime(2020, 1, 1, 6, tzinfo=timezone.utc)
    cycle = finder.locate_range(t0)[0]

    assert cycle.model_id == "retrospective"
    assert cycle.source_id == "RETRO"
    assert len(cycle.files) == 1
    assert "CHRTOUT" in cycle.files[0].url


def test_locate_range_retrospective_enumerates_hourly_files(monkeypatch):
    from nwmfinder import _http

    monkeypatch.setattr(_http, "head", lambda url, **kw: _http.HeadResult(200, None, False, None))

    finder = NwmFinder()
    t0 = datetime(2020, 1, 1, 6, tzinfo=timezone.utc)
    tend = t0 + timedelta(hours=3)
    cycle = finder.locate_range(t0, tend)[0]

    assert [f.init_time for f in cycle.files] == [t0 + timedelta(hours=h) for h in range(4)]


def test_locate_range_retrospective_raises_when_anchor_not_found(monkeypatch):
    from nwmfinder import _http
    from nwmfinder.exceptions import DataNotFoundError
    import pytest

    monkeypatch.setattr(_http, "head", lambda url, **kw: _http.HeadResult(404, None, False, None))

    finder = NwmFinder()
    with pytest.raises(DataNotFoundError):
        finder.locate_range(datetime(2020, 1, 1, 6, tzinfo=timezone.utc))


def test_locate_range_rejects_tend_before_t0():
    import pytest

    finder = NwmFinder()
    t0 = datetime(2026, 9, 1, tzinfo=timezone.utc)
    with pytest.raises(ValueError):
        finder.locate_range(t0, t0 - timedelta(hours=1))

