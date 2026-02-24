"""Tests for the error module."""

import pytest

from roku_tui.errors import ErrorCode, RokuError


class TestErrorCode:
    def test_all_codes_have_three_fields(self):
        for member in ErrorCode:
            assert member.code.startswith("E")
            assert isinstance(member.message, str)
            assert isinstance(member.description, str)

    def test_codes_are_unique(self):
        codes = [m.code for m in ErrorCode]
        assert len(codes) == len(set(codes))

    def test_specific_code_values(self):
        assert ErrorCode.E1001.code == "E1001"
        assert ErrorCode.E1001.message == "Network discovery failed"

        assert ErrorCode.E1007.code == "E1007"
        assert ErrorCode.E1007.message == "Network timeout"

    def test_all_codes_present(self):
        expected = [f"E{i}" for i in range(1001, 1016)]
        actual = [m.code for m in ErrorCode]
        assert actual == expected


class TestRokuError:
    def test_creation_with_code_only(self):
        err = RokuError(ErrorCode.E1001)
        assert err.error_code is ErrorCode.E1001
        assert err.detail == ""
        assert "[E1001]" in str(err)
        assert "Network discovery failed" in str(err)

    def test_creation_with_detail(self):
        err = RokuError(ErrorCode.E1004, "keypress Play failed")
        assert err.error_code is ErrorCode.E1004
        assert err.detail == "keypress Play failed"
        assert "[E1004]" in str(err)
        assert "keypress Play failed" in str(err)

    def test_is_exception(self):
        err = RokuError(ErrorCode.E1002)
        assert isinstance(err, Exception)

    def test_can_be_raised_and_caught(self):
        with pytest.raises(RokuError) as exc_info:
            raise RokuError(ErrorCode.E1008, "192.168.1.1")
        assert exc_info.value.error_code is ErrorCode.E1008
        assert "192.168.1.1" in str(exc_info.value)

    def test_str_without_detail_has_no_colon_suffix(self):
        err = RokuError(ErrorCode.E1002)
        s = str(err)
        assert s == "[E1002] No devices found"

    def test_str_with_detail_includes_colon(self):
        err = RokuError(ErrorCode.E1010, "Permission denied")
        s = str(err)
        assert s == "[E1010] Socket error: Permission denied"
