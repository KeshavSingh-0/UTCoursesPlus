import pytest
from hypothesis import given
from hypothesis import strategies as st

from utcoursesplus.timeutil import parse_clock, parse_days, parse_time_range


def test_ranges():
    assert parse_time_range("11:00 a.m.-12:30 p.m.") == (660, 750)
    assert parse_time_range("12:00 p.m.-1:00 p.m.") == (720, 780)
    assert parse_clock("12:00 a.m.") == 0


def test_days():
    assert parse_days("TTH") == ["T", "TH"]
    assert parse_days("MWF") == ["M", "W", "F"]
    assert parse_days("THF") == ["TH", "F"]


@pytest.mark.parametrize("bad", ["", "XYZ", "MWX"])
def test_bad_days(bad):
    with pytest.raises(ValueError):
        parse_days(bad)


@pytest.mark.parametrize("bad", ["bad time", "9:00 a.m.", "10:00 a.m.-9:00 a.m.", "13:00 p.m.-14:00 p.m."])
def test_bad_ranges(bad):
    with pytest.raises(ValueError):
        parse_time_range(bad)


@given(st.integers(0, 22 * 60), st.integers(1, 120))
def test_roundtrip(start, length):
    def fmt(m):
        h, mi = divmod(m, 60)
        return f"{(h % 12) or 12}:{mi:02d} {'a' if h < 12 else 'p'}.m."

    end = min(start + length, 24 * 60 - 1)
    if end > start:
        assert parse_time_range(f"{fmt(start)}-{fmt(end)}") == (start, end)
