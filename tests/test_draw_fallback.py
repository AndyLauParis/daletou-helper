"""福彩官网不可用时的 500.com 备用源测试（不发起真实网络请求）。"""

from __future__ import annotations

import urllib.error

import pytest

from helper.games import _datachart500, fc3d, kl8, qlc, ssq

SSQ_ROWS = [
    [
        "2", "26136", "09", "11", "22", "27", "30", "33", "05", "",
        "1,164,322,060", "7", "7,654,058", "138", "168,282",
        "417,083,012", "2026-11-26",
    ]
]

QLC_ROWS = [
    ["2", "26136", "02 14 18 19 21 22 24 28", "120", "5,683,156", "0", "2026-11-25"]
]

SD_ROWS = [
    ["2", "2026316", "1 4 5", "10", "101,967,494", "0", "1,040", "", "", "0", "173", "2026-11-26"]
]

KL8_PAGE = '<a href="https://kaijiang.500.com/shtml/kl8/2026316.shtml">2026316</a>'
KL8_XML = (
    "<xml><PeriodicalNum>2026316</PeriodicalNum>"
    "<Result>08,14,15,16,17,21,25,35,36,44,45,46,49,53,61,66,70,71,76,80</Result>"
    "<ResultTime>2026-11-26 21:30:00</ResultTime></xml>"
)


def _blocked(url):
    raise urllib.error.URLError("HTTP Error 403")


def test_ssq_falls_back_to_500(monkeypatch):
    monkeypatch.setattr(ssq, "_request_json", _blocked)
    monkeypatch.setattr(_datachart500, "fetch_rows", lambda game: SSQ_ROWS)
    draws = ssq.fetch_draws(30)
    assert draws[0]["issue"] == "2026136"
    assert draws[0]["date"] == "2026-11-26"
    assert draws[0]["numbers"] == {"red": [9, 11, 22, 27, 30, 33], "blue": [5]}


def test_qlc_falls_back_to_500(monkeypatch):
    monkeypatch.setattr(qlc, "_request_json", _blocked)
    monkeypatch.setattr(_datachart500, "fetch_rows", lambda game: QLC_ROWS)
    draws = qlc.fetch_draws(30)
    assert draws[0]["issue"] == "2026136"
    assert draws[0]["numbers"] == {
        "basic": [2, 14, 18, 19, 21, 22, 24],
        "special": 28,
    }


def test_fc3d_falls_back_to_500(monkeypatch):
    monkeypatch.setattr(fc3d, "_request_json", _blocked)
    monkeypatch.setattr(_datachart500, "fetch_rows", lambda game: SD_ROWS)
    draws = fc3d.fetch_draws(30)
    assert draws[0]["issue"] == "2026316"
    assert draws[0]["numbers"] == {"digits": [1, 4, 5]}


def test_kl8_falls_back_to_500_xml(monkeypatch):
    monkeypatch.setattr(kl8, "_request_json", _blocked)

    def fake_text(url):
        return KL8_PAGE if url == kl8.KL8_PAGE_URL else KL8_XML

    monkeypatch.setattr(kl8, "_request_text", fake_text)
    draws = kl8.fetch_draws(30)
    assert draws[0]["issue"] == "2026316"
    assert draws[0]["date"] == "2026-11-26"
    assert draws[0]["numbers"]["draw"][0] == 8
    assert len(draws[0]["numbers"]["draw"]) == 20


def test_data_error_does_not_hit_fallback(monkeypatch):
    def bad_data(url):
        raise ValueError("数据格式异常")

    def forbidden(game):
        raise AssertionError("数据格式异常时不应请求备用源")

    monkeypatch.setattr(ssq, "_request_json", bad_data)
    monkeypatch.setattr(_datachart500, "fetch_rows", forbidden)
    with pytest.raises(ValueError):
        ssq.fetch_draws(30)


def test_expand_issue():
    assert _datachart500.expand_issue("26136") == "2026136"
    assert _datachart500.expand_issue("2026316") == "2026316"


def test_history_url_issue_width():
    from datetime import datetime

    year = datetime.now().year
    ssq_url = _datachart500.history_url("ssq")
    sd_url = _datachart500.history_url("sd")
    assert f"start={(year - 1) % 100:02d}001" in ssq_url
    assert f"start={year - 1}001" in sd_url
    assert f"end={year}999" in sd_url
