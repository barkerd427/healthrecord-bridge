from __future__ import annotations

import pytest

from healthrecord_bridge.ccda.datetime_utils import normalize_offset, parse_ts, to_instant


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("2019", "2019"),
        ("201909", "2019-09"),
        ("20190920", "2019-09-20"),
        ("20190920165128-0400", "2019-09-20T16:51:28-04:00"),
        ("20190920165128+0000", "2019-09-20T16:51:28+00:00"),
        ("201909201651+0530", "2019-09-20T16:51:00+05:30"),
        ("2019092016-0500", "2019-09-20T16:00:00-05:00"),
        ("20190920165128.123-0400", "2019-09-20T16:51:28.123-04:00"),
        ("20190920165128.123456-0400", "2019-09-20T16:51:28.123-04:00"),
    ],
)
def test_parse_with_offset(raw, expected):
    parsed = parse_ts(raw)
    assert parsed is not None
    assert parsed.value == expected
    assert parsed.truncated is False


def test_time_without_offset_is_truncated_unless_assumed():
    parsed = parse_ts("20190920165128")
    assert parsed is not None
    assert parsed.value == "2019-09-20"
    assert parsed.has_time and parsed.truncated
    assumed = parse_ts("20190920165128", "Z")
    assert assumed is not None
    assert assumed.value == "2019-09-20T16:51:28Z"
    assert not assumed.truncated


@pytest.mark.parametrize(
    "raw", ["", None, "abc", "20191399", "20190931abc", "0000", "20190920251200"]
)
def test_garbage(raw):
    assert parse_ts(raw) is None


def test_to_instant_pads():
    assert to_instant("2019") == "2019-01-01T00:00:00Z"
    assert to_instant("201909", "-05:00") == "2019-09-01T00:00:00-05:00"
    assert to_instant("20190920165128") == "2019-09-20T16:51:28Z"
    assert to_instant("20190920165128-0400") == "2019-09-20T16:51:28-04:00"
    assert to_instant(None) is None


def test_normalize_offset():
    assert normalize_offset(None) is None
    assert normalize_offset("z") == "Z"
    assert normalize_offset("-0500") == "-05:00"
    assert normalize_offset("+05:30") == "+05:30"
    with pytest.raises(ValueError):
        normalize_offset("EST")
