"""Tests for chronoroute.data.omm: OMM JSON parsing, EPOCH as UTC, screening rules,
and keying by NORAD_CAT_ID (6- and 9-digit ids)."""

import calendar
import json
import math
from datetime import datetime, timedelta, timezone
from fractions import Fraction
from functools import cache
from pathlib import Path

import pytest
from sgp4 import omm as sgp4_omm
from sgp4.api import Satrec

from chronoroute.data import omm

REPO = Path(__file__).resolve().parents[2]
PINNED = REPO / "data" / "pinned" / "20261010T1358Z-celestrak"
FETCH_SUPGP_NS = omm.datetime_to_ns(datetime(2026, 10, 10, 14, 2, 22, tzinfo=timezone.utc))
FETCH_GP_NS = omm.datetime_to_ns(datetime(2026, 10, 10, 13, 58, 54, tzinfo=timezone.utc))

# STARLINK-1008 from the pinned SupGP file, as raw JSON text (numbers as CelesTrak wrote them).
TEMPLATE = ('{"OBJECT_NAME":"STARLINK-1008","OBJECT_ID":"2019-074B","EPOCH":"2026-10-10T10:26:41.999971",'
            '"MEAN_MOTION":15.66510296,"ECCENTRICITY":0.0002965,"INCLINATION":53.1445,'
            '"RA_OF_ASC_NODE":229.2781,"ARG_OF_PERICENTER":104.8555,"MEAN_ANOMALY":287.9988,'
            '"EPHEMERIS_TYPE":0,"CLASSIFICATION_TYPE":"C","NORAD_CAT_ID":44714,"ELEMENT_SET_NO":283,'
            '"REV_AT_EPOCH":1,"BSTAR":0.00025777,"MEAN_MOTION_DOT":0.00027475,"MEAN_MOTION_DDOT":0,'
            '"RMS":"0.223","DATA_SOURCE":"SpaceX-E"}')


def obj(**changes):
    """The template object (numbers as JsonNumber) with fields replaced or removed (value None)."""
    data = omm.parse_omm_json("[" + TEMPLATE + "]")[0]
    for key, value in changes.items():
        if value is None:
            data.pop(key, None)
        elif isinstance(value, (int, float)) and not isinstance(value, bool):
            data[key] = omm.JsonNumber(json.dumps(value), value)
        else:
            data[key] = value
    return data


@cache
def raw_objects(name):
    return omm.parse_omm_json((PINNED / name).read_bytes())


# ------------------------------------------------------------------ parsing

def test_numbers_keep_their_source_text():
    data = omm.parse_omm_json(b'[{"a": 9.9687e-5, "b": 0, "c": "x", "d": 15.66510296, "e": null}]')
    a = data[0]["a"]
    assert isinstance(a, omm.JsonNumber) and a.text == "9.9687e-5" and a.value == 9.9687e-05
    assert data[0]["b"].text == "0" and data[0]["b"].value == 0 and isinstance(data[0]["b"].value, int)
    assert data[0]["c"] == "x" and data[0]["e"] is None
    assert omm.plain(data) == [{"a": 9.9687e-5, "b": 0, "c": "x", "d": 15.66510296, "e": None}]


@pytest.mark.parametrize("raw", [b"{}", b'"x"', b"[NaN]", b'[{"a": Infinity}]', b"[1,", b""])
def test_parse_refuses_non_arrays_and_non_json(raw):
    with pytest.raises(omm.OmmFormatError):
        omm.parse_omm_json(raw)


# ------------------------------------------------------------------- EPOCH

def test_epoch_is_read_as_utc_exactly():
    assert omm.parse_epoch_ns("1970-01-01T00:00:00") == 0
    whole = calendar.timegm((2026, 10, 10, 14, 2, 22, 0, 0, 0))
    assert omm.parse_epoch_ns("2026-10-10T14:02:22") == whole * 10**9
    assert omm.parse_epoch_ns("2026-10-10T14:02:22.000019") == whole * 10**9 + 19_000
    assert omm.parse_epoch_ns("2026-10-10T14:02:22.5") == whole * 10**9 + 500_000_000
    # more than 9 fraction digits: cut, not rounded
    assert omm.parse_epoch_ns("2026-10-10T14:02:22.1234567899") == whole * 10**9 + 123_456_789
    # same instant as an aware datetime (UTC), microseconds exact
    moment = datetime(2026, 10, 8, 17, 33, 41, 999990, tzinfo=timezone.utc)
    assert omm.parse_epoch_ns("2026-10-08T17:33:41.999990") == omm.datetime_to_ns(moment)


@pytest.mark.parametrize("bad", [
    "2026-10-10T14:02:22Z",          # CelesTrak sends no zone; a Z means a different format
    "2026-10-10 14:02:22",           # space instead of T
    "2026-13-10T14:02:22",           # month 13
    "2026-02-30T00:00:00",           # 30 February
    "2026-10-10T14:02:22\n",         # trailing newline (Python's $ would accept it)
    "2026-10-10T14:02:22.",          # dot without digits
    "２０２６-10-10T14:02:22",        # full-width digits match \\d but not [0-9]
    "26-10-10T14:02:22",
])
def test_bad_epochs_are_refused(bad):
    with pytest.raises(ValueError):
        omm.parse_epoch_ns(bad)


def test_format_utc_ns_round_trips():
    for text in ("2026-10-10T14:02:22Z", "2026-10-08T17:33:41.99999Z", "1970-01-01T00:00:00.000000001Z"):
        assert omm.format_utc_ns(omm.parse_epoch_ns(text[:-1])) == text


def test_datetime_to_ns_refuses_naive_datetimes():
    with pytest.raises(ValueError):
        omm.datetime_to_ns(datetime(2026, 10, 10))
    ist = timezone(timedelta(hours=5, minutes=30))
    assert omm.datetime_to_ns(datetime(2026, 10, 10, 19, 32, 22, tzinfo=ist)) == FETCH_SUPGP_NS


def test_ns_to_jd_matches_sgp4_jday():
    from sgp4.api import jday
    jd, fr = omm.ns_to_jd(FETCH_SUPGP_NS)
    assert (jd, fr) == jday(2026, 10, 10, 14, 2, 22)


# --------------------------------------------------------- invalid objects

def test_template_is_valid():
    assert omm.object_problem(obj()) is None


@pytest.mark.parametrize("changes, fragment", [
    ({"MEAN_MOTION": None}, "missing MEAN_MOTION"),
    ({"OBJECT_NAME": ""}, "OBJECT_NAME"),
    ({"OBJECT_ID": 5}, "OBJECT_ID"),
    ({"MEAN_MOTION": "15.6"}, "MEAN_MOTION"),                 # a string is not a number
    ({"INCLINATION": True}, "INCLINATION"),                   # neither is a boolean
    ({"BSTAR": float("inf")}, "BSTAR"),
    ({"RMS": 0.2}, "RMS"),                                     # optional, but a string when present
    ({"EPOCH": "2026-10-10T10:26:41Z"}, "EPOCH"),
    ({"NORAD_CAT_ID": 0}, "NORAD_CAT_ID"),
    ({"NORAD_CAT_ID": -5}, "NORAD_CAT_ID"),
    ({"NORAD_CAT_ID": 44714.5}, "NORAD_CAT_ID"),
    ({"EPHEMERIS_TYPE": 2}, "EPHEMERIS_TYPE"),
    ({"CLASSIFICATION_TYPE": "S"}, "CLASSIFICATION_TYPE"),
])
def test_invalid_objects_are_named(changes, fragment):
    problem = omm.object_problem(obj(**changes))
    assert problem is not None and fragment in problem


def test_null_optional_field_is_invalid_and_absent_one_is_fine():
    # The website converter treats a null RMS as invalid (typeof null is not "string").
    assert omm.object_problem(obj(RMS=None, DATA_SOURCE=None)) is None       # absent: fine (GP)
    data = obj()
    data["RMS"] = None
    assert "RMS" in omm.object_problem(data)


def test_integral_float_norad_id_is_accepted_like_javascript():
    record = omm.OmmRecord.from_object(obj(NORAD_CAT_ID=44714.0))
    assert record.norad == 44714 and isinstance(record.norad, int)


def test_non_object_is_invalid():
    assert omm.object_problem([1, 2]) == "not a JSON object"


# ----------------------------------------------------------------- screening

def test_screen_applies_the_rules_in_contract_order():
    fetched = omm.parse_epoch_ns("2026-10-13T10:26:41.999971")       # exactly 3 days after the epoch
    objects = [
        obj(),                                                           # 0 kept (exactly 3 days: not stale)
        obj(NORAD_CAT_ID=50001, EPOCH="2026-10-10T10:26:41.999970"),     # 1 stale by 1 microsecond
        obj(NORAD_CAT_ID=50002, ECCENTRICITY=1.2),                       # 2 sgp4 error 1 (e >= 1)
        obj(NORAD_CAT_ID=50003, EPHEMERIS_TYPE=4),                       # 3 invalid
        obj(NORAD_CAT_ID=50004, EPOCH="2026-10-11T00:00:00.000000"),     # 4 kept, then replaced by 5
        obj(NORAD_CAT_ID=50004, EPOCH="2026-10-12T00:00:00.000000"),     # 5 newer: kept
        obj(NORAD_CAT_ID=50004, EPOCH="2026-10-12T00:00:00.000000"),     # 6 tie: first one stays
        obj(NORAD_CAT_ID=50005, EPHEMERIS_TYPE=4, EPOCH="2000-01-01T00:00:00"),  # 7 invalid beats stale
        obj(NORAD_CAT_ID=50002),                                         # 8 same id as the sgp4 failure: kept
        "not an object",                                                 # 9 invalid, no id
    ]
    result = omm.screen_objects(objects, fetched)
    assert result.excluded == {"invalid": 3, "stale_epoch": 1, "sgp4_error": 1, "duplicate": 2}
    assert list(result.excluded) == list(omm.EXCLUSION_REASONS)
    assert [r.norad for r in result.kept] == [44714, 50002, 50004]
    assert {r.norad: r.index for r in result.kept}[50004] == 5
    assert result.count_raw == len(objects) == len(result.kept) + sum(result.excluded.values())
    by_index = {e.index: e for e in result.exclusions}
    assert by_index[1].reason == "stale_epoch" and by_index[2].reason == "sgp4_error"
    assert by_index[4].reason == "duplicate" and by_index[6].reason == "duplicate"
    assert by_index[7].reason == "invalid" and by_index[9].norad is None
    assert set(result.satrecs) == {44714, 50002, 50004}


def test_stale_threshold_can_be_a_fraction_of_a_day():
    fetched = omm.parse_epoch_ns("2026-10-10T22:26:41.999971")        # epoch + 12 h
    assert omm.screen_objects([obj()], fetched, max_epoch_age_days=Fraction(1, 2)).excluded["stale_epoch"] == 0
    assert omm.screen_objects([obj()], fetched + 1, max_epoch_age_days=0.5).excluded["stale_epoch"] == 1
    with pytest.raises(ValueError):
        omm.screen_objects([obj()], fetched, max_epoch_age_days=0)


def test_epoch_summary_uses_the_lower_median():
    objects = [obj(NORAD_CAT_ID=60000 + i, EPOCH=f"2026-10-10T0{i}:00:00.000000") for i in range(4)]
    result = omm.screen_objects(objects, omm.parse_epoch_ns("2026-10-10T12:00:00"))
    assert result.epoch_summary() == {"epoch_min": "2026-10-10T00:00:00.000000Z",
                                      "epoch_median": "2026-10-10T01:00:00.000000Z",
                                      "epoch_max": "2026-10-10T03:00:00.000000Z"}


# ------------------------------------------------- NORAD ids beyond 5 digits

def test_sgp4_itself_refuses_ids_above_339999():
    """Why we never hand sgp4 the real id: its satnum stops at 339999 (Alpha-5 'Z9999')."""
    fields = omm.plain(obj(NORAD_CAT_ID=340000))
    with pytest.raises(ValueError):
        sgp4_omm.initialize(Satrec(), fields)


@pytest.mark.parametrize("norad", [99999, 100001, 339999, 340000, 799123456, 123456789])
def test_large_norad_ids_load_and_propagate_like_any_other(norad):
    fetched = FETCH_SUPGP_NS
    reference = omm.screen_objects([obj()], fetched)
    result = omm.screen_objects([obj(NORAD_CAT_ID=norad)], fetched)
    assert result.excluded == dict.fromkeys(omm.EXCLUSION_REASONS, 0)
    (record,) = result.kept
    assert record.norad == norad                                     # the key is the JSON id
    sat = result.satrecs[norad]
    assert sat.satnum == omm.SATNUM_PLACEHOLDER                      # never the real id
    jd, fr = omm.ns_to_jd(fetched)
    assert sat.sgp4(jd, fr) == reference.satrecs[44714].sgp4(jd, fr)   # bit-identical orbit


def test_placeholder_satnum_does_not_change_the_orbit():
    with_real_id, with_placeholder = Satrec(), Satrec()
    sgp4_omm.initialize(with_real_id, omm.plain(obj()))
    sgp4_omm.initialize(with_placeholder, omm.OmmRecord.from_object(obj()).sgp4_fields())
    assert with_real_id.satnum == 44714 and with_placeholder.satnum == 0
    for minutes in (0.0, 90.0, 1440.0, -600.0):
        assert with_real_id.sgp4_tsince(minutes) == with_placeholder.sgp4_tsince(minutes)


def test_epoch_without_fraction_is_accepted():
    """sgp4.omm parses EPOCH with '%S.%f'; we add '.0', which is the same instant."""
    result = omm.screen_objects([obj(EPOCH="2026-10-10T10:26:41")], FETCH_SUPGP_NS)
    assert len(result.kept) == 1
    assert result.kept[0].sgp4_fields()["EPOCH"] == "2026-10-10T10:26:41.0"
    assert result.kept[0].epoch == "2026-10-10T10:26:41"             # the record keeps the source text


def test_records_from_objects_refuses_duplicates_and_invalid():
    with pytest.raises(ValueError):
        omm.records_from_objects([obj(), obj()])
    with pytest.raises(ValueError):
        omm.records_from_objects([obj(EPHEMERIS_TYPE=2)])


# ------------------------------------------------- the pinned real snapshot

def test_pinned_supgp_parses_with_zero_failures():
    """Acceptance (plan P2): 0 parse failures; 6-digit ids present."""
    objects = raw_objects("starlink_supgp.json")
    result = omm.screen_objects(objects, FETCH_SUPGP_NS)
    assert result.count_raw == 11_130
    assert result.excluded == {"invalid": 0, "stale_epoch": 0, "sgp4_error": 0, "duplicate": 0}
    six = [r.norad for r in result.kept if r.norad >= 100_000]
    assert len(six) == 472 and max(six) == 100_880
    assert all(r.values["CLASSIFICATION_TYPE"] == "C" for r in result.kept)


def test_pinned_gp_counts_match_the_research_measurement():
    """06_research_live-data.md section 1: 11,103 objects, 5 older than 3 days, 446 ids >= 100000."""
    result = omm.screen_objects(raw_objects("starlink_gp.json"), FETCH_GP_NS)
    assert result.count_raw == 11_103
    assert result.excluded == {"invalid": 0, "stale_epoch": 5, "sgp4_error": 0, "duplicate": 0}
    assert sum(r.norad >= 100_000 for r in result.kept) == 446
    assert sum(r.is_dtc for r in result.kept) == 637
    assert all(math.isfinite(r.mean_motion) for r in result.kept)
