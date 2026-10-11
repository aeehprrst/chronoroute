"""
omm.py
------
Reads CelesTrak OMM JSON (the GP and SupGP `FORMAT=json` files) and decides,
object by object, which element sets are usable.

Why this module is careful (each point is a real trap in today's data):

  * NORAD catalogue numbers ran past 99999 on 2026-07-11, so there are 6-digit
    ids such as 100001, and CelesTrak expects 9-digit ids in future. The sgp4
    library stores the number as `satnum` and refuses anything above 339999
    (the largest Alpha-5 number). So we key EVERY object by NORAD_CAT_ID read
    from the JSON, and hand sgp4 a placeholder satnum: the catalogue number has
    no effect on the orbit (a test proves the positions are identical).
  * EPOCH strings have no "Z" but are UTC. We turn them into exact integer
    nanoseconds ourselves, so "older than 3 days" is an exact comparison and
    not a floating-point guess.
  * The website must receive the numbers exactly as CelesTrak wrote them, so
    the parser keeps every number's source text (JsonNumber) next to its value.

Screening rules (the website data contract, web/DATA_CONTRACT.md). They are
applied in this order and each object is counted under the first rule it breaks:

  1. invalid      a required field is missing or has the wrong type; EPOCH is
                  not YYYY-MM-DDTHH:MM:SS[.ffffff]; NORAD_CAT_ID is not a
                  positive integer; EPHEMERIS_TYPE is not 0 (SGP4);
                  CLASSIFICATION_TYPE is not "U" or "C"
  2. stale_epoch  fetched_utc - EPOCH > 3 days
  3. sgp4_error   sgp4 cannot initialise the element set, or cannot propagate
                  it to the fetch instant
  4. duplicate    a second element set for a NORAD id that is already kept; the
                  newest EPOCH wins (on an exact tie the first one in the file
                  stays, like the website's converter)

Labels: the element sets are REAL (public data); everything computed from them
is DERIVED.
"""

import json
import math
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from fractions import Fraction
from types import MappingProxyType

from sgp4 import omm as _sgp4_omm
from sgp4.api import SGP4_ERRORS, Satrec

# Column order of the website's omm.min.json = CelesTrak's key order for SupGP.
OMM_FIELDS = (
    "OBJECT_NAME", "OBJECT_ID", "EPOCH", "MEAN_MOTION", "ECCENTRICITY",
    "INCLINATION", "RA_OF_ASC_NODE", "ARG_OF_PERICENTER", "MEAN_ANOMALY",
    "EPHEMERIS_TYPE", "CLASSIFICATION_TYPE", "NORAD_CAT_ID", "ELEMENT_SET_NO",
    "REV_AT_EPOCH", "BSTAR", "MEAN_MOTION_DOT", "MEAN_MOTION_DDOT",
    "RMS", "DATA_SOURCE",
)
# RMS and DATA_SOURCE exist only in SupGP, so they are optional everywhere.
OPTIONAL_FIELDS = ("RMS", "DATA_SOURCE")
REQUIRED_FIELDS = tuple(f for f in OMM_FIELDS if f not in OPTIONAL_FIELDS)
STRING_FIELDS = frozenset({"OBJECT_NAME", "OBJECT_ID", "EPOCH", "CLASSIFICATION_TYPE"})

EXCLUSION_REASONS = ("invalid", "stale_epoch", "sgp4_error", "duplicate")   # contract order
MAX_EPOCH_AGE_DAYS = 3

NS_PER_S = 1_000_000_000
NS_PER_DAY = 86_400 * NS_PER_S
JD_UNIX_EPOCH = 2440587.5            # Julian date of 1970-01-01T00:00:00 UTC
_UNIX_EPOCH_ORDINAL = datetime(1970, 1, 1).toordinal()

# What sgp4 is told the catalogue number is. Any value 0..339999 gives the
# same orbit; 0 makes it obvious that it is not a real id.
SATNUM_PLACEHOLDER = 0

# EPOCH as the contract allows it. [0-9] (not \d, which also matches other
# scripts' digits) and fullmatch (Python's "$" would accept a trailing newline).
_EPOCH_RE = re.compile(r"([0-9]{4})-([0-9]{2})-([0-9]{2})T([0-9]{2}):([0-9]{2}):([0-9]{2})(?:\.([0-9]+))?")


class OmmFormatError(ValueError):
    """The raw file is not a JSON array of OMM objects at all."""


class JsonNumber:
    """A JSON number together with the exact text it had in the source file.

    json.loads would turn 9.9687e-5 into the float 9.9687e-05 and print it
    back differently. Keeping the text lets omm.min.json carry CelesTrak's
    numbers verbatim, while `value` is what every calculation uses.
    """

    __slots__ = ("text", "value")

    def __init__(self, text, value):
        self.text = text
        self.value = value

    def __repr__(self):
        return f"JsonNumber({self.text})"


def _reject_constant(name):
    # Python's json accepts NaN / Infinity; real JSON (and the browser) does not.
    raise ValueError(f"{name} is not valid JSON")


def loads_keep_numbers(raw):
    """json.loads, but every number becomes a JsonNumber (text + value).

    Strings, null and booleans stay ordinary Python values. NaN/Infinity are
    refused, as in standard JSON. Raises OmmFormatError on invalid JSON.
    """
    try:
        return json.loads(raw,
                          parse_float=lambda text: JsonNumber(text, float(text)),
                          parse_int=lambda text: JsonNumber(text, int(text)),
                          parse_constant=_reject_constant)
    except ValueError as exc:            # JSONDecodeError is a ValueError
        raise OmmFormatError(f"not valid JSON: {exc}") from None


def parse_omm_json(raw):
    """Parse raw OMM JSON (bytes or str) into a list of dicts (numbers as JsonNumber).

    Raises OmmFormatError if the file is not valid JSON or not a JSON array.
    """
    data = loads_keep_numbers(raw)
    if not isinstance(data, list):
        raise OmmFormatError("an OMM file must hold a JSON array of objects")
    return data


def plain(value):
    """Strip JsonNumber wrappers: return ordinary JSON values (int/float/str/...)."""
    if isinstance(value, JsonNumber):
        return value.value
    if isinstance(value, dict):
        return {key: plain(item) for key, item in value.items()}
    if isinstance(value, list):
        return [plain(item) for item in value]
    return value


# --------------------------------------------------------------------- time

def parse_epoch_ns(text):
    """EPOCH string (UTC, no zone) -> integer nanoseconds since 1970-01-01T00:00Z.

    Exact: no floats are involved. Digits beyond nanoseconds are cut off.
    Raises ValueError for anything the contract's EPOCH pattern rejects, and
    for impossible dates such as month 13.
    """
    if not isinstance(text, str):
        raise ValueError("EPOCH must be a string")
    match = _EPOCH_RE.fullmatch(text)
    if match is None:
        raise ValueError(f"EPOCH {text!r} is not YYYY-MM-DDTHH:MM:SS[.ffffff]")
    year, month, day, hour, minute, second = (int(g) for g in match.groups()[:6])
    moment = datetime(year, month, day, hour, minute, second)   # validates the ranges
    fraction = match.group(7) or ""
    nanos = int(fraction[:9].ljust(9, "0"))
    days = moment.toordinal() - _UNIX_EPOCH_ORDINAL
    seconds = days * 86_400 + hour * 3600 + minute * 60 + second
    return seconds * NS_PER_S + nanos


def datetime_to_ns(moment):
    """Aware datetime -> integer UTC nanoseconds (microseconds kept exactly)."""
    if moment.tzinfo is None:
        raise ValueError("use a timezone-aware datetime (UTC); a naive one is ambiguous")
    moment = moment.astimezone(timezone.utc)
    days = moment.toordinal() - _UNIX_EPOCH_ORDINAL
    seconds = days * 86_400 + moment.hour * 3600 + moment.minute * 60 + moment.second
    return seconds * NS_PER_S + moment.microsecond * 1000


def format_utc_ns(ns):
    """Integer UTC nanoseconds -> ISO 8601 text ending in Z.

    Whole seconds print without a fraction (2026-10-10T14:02:22Z); otherwise
    the fraction keeps every non-zero digit.
    """
    seconds, nanos = divmod(ns, NS_PER_S)
    days, rest = divmod(seconds, 86_400)
    date = datetime.fromordinal(days + _UNIX_EPOCH_ORDINAL)
    hour, rest = divmod(rest, 3600)
    minute, second = divmod(rest, 60)
    text = f"{date:%Y-%m-%d}T{hour:02d}:{minute:02d}:{second:02d}"
    if nanos:
        text += "." + f"{nanos:09d}".rstrip("0")
    return text + "Z"


def ns_to_jd(ns):
    """Integer UTC nanoseconds -> (jd, fr) as sgp4 wants them.

    jd is the Julian date of the preceding midnight (always ...5) and fr the
    fraction of the day, so the large and small parts never mix in one float.
    """
    days, rest = divmod(ns, NS_PER_DAY)
    return JD_UNIX_EPOCH + days, rest / NS_PER_DAY


# ------------------------------------------------------------- one object

def _finite_number(value):
    if not isinstance(value, JsonNumber):
        return False
    try:
        return math.isfinite(float(value.value))
    except OverflowError:           # an integer too big for a double is "Infinity" in JS
        return False


def object_problem(obj):
    """Return why an OMM object is invalid (contract rule 1), or None if it is fine."""
    if not isinstance(obj, dict):
        return "not a JSON object"
    for name in REQUIRED_FIELDS:
        if name not in obj:
            return f"missing {name}"
        value = obj[name]
        if name in STRING_FIELDS:
            if not isinstance(value, str) or value == "":
                return f"{name} must be a non-empty string"
        elif not _finite_number(value):
            return f"{name} must be a finite number"
    for name in OPTIONAL_FIELDS:
        if name in obj and not isinstance(obj[name], str):
            return f"{name} must be a string when present"
    try:
        parse_epoch_ns(obj["EPOCH"])
    except ValueError as exc:
        return str(exc)
    norad = obj["NORAD_CAT_ID"].value
    if not (float(norad).is_integer() and norad > 0):
        return f"NORAD_CAT_ID {obj['NORAD_CAT_ID'].text} is not a positive integer"
    if obj["EPHEMERIS_TYPE"].value != 0:
        return f"EPHEMERIS_TYPE {obj['EPHEMERIS_TYPE'].text} is not 0 (SGP4)"
    if obj["CLASSIFICATION_TYPE"] not in ("U", "C"):
        return f"CLASSIFICATION_TYPE {obj['CLASSIFICATION_TYPE']!r} is not 'U' or 'C'"
    return None


@dataclass(frozen=True)
class OmmRecord:
    """One valid OMM element set, keyed by the NORAD id from the JSON.

    values : every field the source object had, as plain JSON values, in the
             source's key order
    tokens : numeric field -> its exact source text (for verbatim output)
    index  : position in the raw array (used for tie-breaks and messages)
    """

    norad: int
    index: int
    epoch_ns: int
    values: MappingProxyType
    tokens: MappingProxyType

    @classmethod
    def from_object(cls, obj, index=0):
        """Build a record from a parsed object that object_problem() accepted."""
        problem = object_problem(obj)
        if problem is not None:
            raise ValueError(f"object {index}: {problem}")
        values = {key: plain(item) for key, item in obj.items()}
        tokens = {key: item.text for key, item in obj.items() if isinstance(item, JsonNumber)}
        return cls(norad=int(obj["NORAD_CAT_ID"].value), index=index,
                   epoch_ns=parse_epoch_ns(obj["EPOCH"]),
                   values=MappingProxyType(values), tokens=MappingProxyType(tokens))

    # Convenience accessors (all REAL, straight from the element set).
    @property
    def name(self):
        return self.values["OBJECT_NAME"]

    @property
    def epoch(self):
        return self.values["EPOCH"]

    @property
    def is_dtc(self):
        """Direct-to-Cell satellites carry "[DTC]" in their catalogue name."""
        return "[DTC]" in self.values["OBJECT_NAME"]

    @property
    def mean_motion(self):           # revolutions per day (Kozai mean motion)
        return float(self.values["MEAN_MOTION"])

    @property
    def eccentricity(self):
        return float(self.values["ECCENTRICITY"])

    @property
    def inclination(self):           # degrees
        return float(self.values["INCLINATION"])

    @property
    def raan(self):                  # right ascension of the ascending node, degrees, at EPOCH
        return float(self.values["RA_OF_ASC_NODE"])

    @property
    def arg_of_pericenter(self):     # degrees
        return float(self.values["ARG_OF_PERICENTER"])

    @property
    def mean_anomaly(self):          # degrees
        return float(self.values["MEAN_ANOMALY"])

    @property
    def mean_motion_dot(self):       # rev/day^2 / 2, as published
        return float(self.values["MEAN_MOTION_DOT"])

    def sgp4_fields(self):
        """The fields for sgp4.omm.initialize, made safe for it.

        * NORAD_CAT_ID -> SATNUM_PLACEHOLDER: sgp4 refuses ids above 339999,
          and the id has no effect on the orbit.
        * EPOCH: sgp4 parses it with '%S.%f', which needs 1-6 fraction digits.
          A missing fraction becomes '.0' (same instant); more than 6 digits
          are cut to microseconds (sgp4 cannot represent finer anyway).
        """
        fields = dict(self.values)
        fields["NORAD_CAT_ID"] = SATNUM_PLACEHOLDER
        epoch = fields["EPOCH"]
        if "." not in epoch:
            epoch += ".0"
        else:
            head, frac = epoch.split(".", 1)
            epoch = f"{head}.{frac[:6]}"
        fields["EPOCH"] = epoch
        return fields


def make_satrec(record):
    """sgp4 Satrec for a record, built with sgp4.omm.initialize (WGS72, as SGP4 expects)."""
    sat = Satrec()
    _sgp4_omm.initialize(sat, record.sgp4_fields())
    return sat


def sgp4_problem(record, jd, fr):
    """(problem text or None, Satrec or None) for the SGP4 check at (jd, fr)."""
    try:
        sat = make_satrec(record)
    except Exception as exc:            # sgp4 raises ValueError/TypeError on odd input
        return f"sgp4 could not initialise it: {exc}", None
    if sat.error:
        return f"sgp4 initialisation error {sat.error}: {SGP4_ERRORS.get(sat.error, '?')}", None
    error, position, _ = sat.sgp4(jd, fr)
    if error:
        return f"sgp4 error {error} at the fetch time: {SGP4_ERRORS.get(error, '?')}", None
    if not all(math.isfinite(x) for x in position):
        return "sgp4 returned a non-finite position at the fetch time", None
    return None, sat


# ---------------------------------------------------------------- screening

@dataclass(frozen=True)
class Exclusion:
    """One object left out, and why."""

    reason: str            # one of EXCLUSION_REASONS
    index: int             # position in the raw array
    norad: int | None      # None when the object was too broken to have one
    detail: str


@dataclass(frozen=True)
class ScreenResult:
    """The outcome of screen_objects().

    kept        valid, fresh, propagatable records, one per NORAD id, sorted by id
    count_raw   number of objects in the raw array
    exclusions  every left-out object with its reason
    check_ns    the instant (UTC ns) of the stale-epoch rule and the SGP4 check
    satrecs     NORAD id -> the Satrec built during the check (reused by the
                propagator so 11k element sets are initialised once)
    """

    kept: tuple
    count_raw: int
    exclusions: tuple
    check_ns: int
    max_epoch_age_days: object
    satrecs: MappingProxyType = field(repr=False, compare=False)

    @property
    def excluded(self):
        """Counts per reason, in contract order (zero when none)."""
        counts = dict.fromkeys(EXCLUSION_REASONS, 0)
        for item in self.exclusions:
            counts[item.reason] += 1
        return counts

    def epoch_summary(self):
        """Oldest, (lower) median and newest EPOCH of the kept sets, with 'Z' appended.

        The lower median is used for an even count, so it is always an epoch
        that really occurs in the data (the website contract's rule).
        """
        return epoch_summary(self.kept)


def epoch_summary(records):
    if not records:
        raise ValueError("no element sets")
    ordered = sorted(records, key=lambda r: (r.epoch_ns, r.epoch))
    lower_median = ordered[(len(ordered) - 1) // 2]
    return {"epoch_min": ordered[0].epoch + "Z",
            "epoch_median": lower_median.epoch + "Z",
            "epoch_max": ordered[-1].epoch + "Z"}


def screen_objects(objects, fetched_ns, *, max_epoch_age_days=MAX_EPOCH_AGE_DAYS):
    """Apply the four exclusion rules (module docstring) to parsed OMM objects.

    objects            list from parse_omm_json()
    fetched_ns         download time in UTC ns (from the HTTP Date header);
                       both the stale rule and the SGP4 check use it
    max_epoch_age_days stale threshold; an int or Fraction keeps it exact
    """
    if isinstance(max_epoch_age_days, float):
        max_epoch_age_days = Fraction(max_epoch_age_days)
    max_age_ns = Fraction(max_epoch_age_days) * NS_PER_DAY
    if max_age_ns <= 0:
        raise ValueError("max_epoch_age_days must be positive")
    jd, fr = ns_to_jd(fetched_ns)

    exclusions = []
    kept = {}
    satrecs = {}
    for index, obj in enumerate(objects):
        problem = object_problem(obj)
        if problem is not None:
            norad = None
            if isinstance(obj, dict) and _finite_number(obj.get("NORAD_CAT_ID")) \
                    and float(obj["NORAD_CAT_ID"].value).is_integer():
                norad = int(obj["NORAD_CAT_ID"].value)
            exclusions.append(Exclusion("invalid", index, norad, problem))
            continue
        record = OmmRecord.from_object(obj, index)
        age_ns = fetched_ns - record.epoch_ns
        if age_ns > max_age_ns:
            exclusions.append(Exclusion("stale_epoch", index, record.norad,
                                        f"epoch {record.epoch} is {age_ns / NS_PER_DAY:.2f} days old"))
            continue
        problem, sat = sgp4_problem(record, jd, fr)
        if problem is not None:
            exclusions.append(Exclusion("sgp4_error", index, record.norad, problem))
            continue
        previous = kept.get(record.norad)
        if previous is None:
            kept[record.norad] = record
            satrecs[record.norad] = sat
        elif record.epoch_ns > previous.epoch_ns:
            exclusions.append(Exclusion("duplicate", previous.index, previous.norad,
                                        f"older than the element set at index {index}"))
            kept[record.norad] = record
            satrecs[record.norad] = sat
        else:
            exclusions.append(Exclusion("duplicate", index, record.norad,
                                        f"not newer than the element set at index {previous.index}"))

    ordered = tuple(kept[norad] for norad in sorted(kept))
    exclusions.sort(key=lambda item: item.index)
    return ScreenResult(kept=ordered, count_raw=len(objects), exclusions=tuple(exclusions),
                        check_ns=fetched_ns, max_epoch_age_days=max_epoch_age_days,
                        satrecs=MappingProxyType(satrecs))


def records_from_objects(objects):
    """Records for already-screened objects (e.g. rows of a website snapshot).

    Raises ValueError on the first invalid object or duplicate NORAD id: a
    published snapshot must already be clean.
    """
    records = []
    seen = set()
    for index, obj in enumerate(objects):
        record = OmmRecord.from_object(obj, index)
        if record.norad in seen:
            raise ValueError(f"NORAD id {record.norad} appears twice")
        seen.add(record.norad)
        records.append(record)
    return tuple(sorted(records, key=lambda r: r.norad))
