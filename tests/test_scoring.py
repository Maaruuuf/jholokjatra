import datetime as dt

from app.domain import Alert, DataBundle, Metric
from app.schemas import Preferences, Verdict
from app.scoring import Scales, assess_all, flood_metrics, pick_best, scales_from

D = dt.date(2026, 11, 5)


def bundle(**metrics) -> DataBundle:
    ms = {k: Metric(v, "test", "http://x", "ref1") for k, v in metrics.items()}
    return DataBundle(dest_key="t", metrics={D.isoformat(): ms})


def verdict(b, scales=Scales()):
    return assess_all([D], b, scales)[0]


def test_calm_day_is_go():
    v = verdict(bundle(precipitation_sum=1, wind_gusts_10m_max=20, temperature_2m_max=30))
    assert v.verdict == Verdict.GO and v.score == 100 and not v.reasons


def test_heavy_rain_avoid_with_evidence():
    v = verdict(bundle(precipitation_sum=80))
    assert v.verdict == Verdict.AVOID
    r = v.reasons[0]
    assert r.ref == "ref1" and r.value == 80 and r.threshold == 60


def test_caution_band():
    assert verdict(bundle(wind_gusts_10m_max=50)).verdict == Verdict.CAUTION


def test_waves_only_matter_for_sea_trips():
    b = bundle(wave_height_max=3.0)
    assert verdict(b).verdict == Verdict.GO
    b.sea_trip = True
    assert verdict(b).verdict == Verdict.AVOID


def test_missing_marine_data_on_sea_trip_is_caution():
    b = bundle(precipitation_sum=1)
    b.sea_trip = True
    v = verdict(b)
    assert v.verdict == Verdict.CAUTION and "unavailable" in v.reasons[0].label


def test_preferences_make_thresholds_stricter():
    b = bundle(wave_height_max=1.2)
    b.sea_trip = True
    assert verdict(b).verdict == Verdict.GO
    assert verdict(b, scales_from(Preferences(motion_sickness=True))).verdict == Verdict.CAUTION


def test_gdacs_red_cyclone_vetoes_good_weather():
    b = bundle(precipitation_sum=1)
    b.alerts = [Alert("TC", "TESTCYCLONE", "Red", 21, 90, D, D + dt.timedelta(days=2), 150.0, "http://g", "gref")]
    v = verdict(b)
    assert v.verdict == Verdict.AVOID
    assert v.agents["weather"] == Verdict.GO and v.agents["safety"] == Verdict.AVOID


def test_flood_ratio_heuristic():
    data = {"daily": {"time": ["a", "b", "c", "d"], "river_discharge": [100, 120, 200, 300]}}
    m = flood_metrics(data, "u", "r")
    assert m["d"]["flood_ratio"].value == 3.0


def test_pick_best_prefers_go_then_caution():
    days = assess_all([D, D + dt.timedelta(1)], DataBundle("t", metrics={
        D.isoformat(): {"precipitation_sum": Metric(25, "t", "", "")},
        (D + dt.timedelta(1)).isoformat(): {"precipitation_sum": Metric(1, "t", "", "")}}), Scales())
    best, caution = pick_best(days)
    assert best == [D + dt.timedelta(1)] and not caution
    best, caution = pick_best([days[0]])
    assert best == [D] and caution
