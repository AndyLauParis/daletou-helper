"""体彩数字型适配器测试：大乐透、排列3、排列5、七星彩。

所有网络请求均被 mock，不依赖实时网络。
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from core import rules as core_rules
from core import store as core_store
from helper import config
from helper.games import cache, dlt, pl3, pl5, qxc
from helper_app import app

# ---------- 测试替身 ----------


class FakeResponse:
    def __init__(self, payload=None, content: bytes | None = None):
        self.payload = payload
        self.content = content
        self.text = (
            content.decode("gb2312", errors="replace") if content is not None else ""
        )

    def raise_for_status(self) -> None:
        return None

    def json(self):
        if self.payload is None:
            raise ValueError("no json body")
        return self.payload


CORE_DRAWS = [
    {
        "issue": "26134",
        "date": "2026-11-22",
        "front": [5, 4, 3, 2, 1],
        "back": [12, 11],
        "pool": 100,
    },
    {
        "issue": "26135",
        "date": "2026-11-24",
        "front": [1, 2, 3, 4, 5],
        "back": [1, 2],
        "pool": 123456789,
    },
]

PL3_DATA = {
    "success": True,
    "value": {
        "list": [
            {
                "lotteryDrawNum": "26311",
                "lotteryDrawResult": "9 8 7",
                "lotteryDrawTime": "2026-11-21",
                "lotterySaleAmount": "1,000,000",
                "poolBalanceAfterdraw": "0",
            },
            {
                "lotteryDrawNum": "26313",
                "lotteryDrawResult": "0 3 6",
                "lotteryDrawTime": "2026-11-23 20:30:00",
                "lotterySaleAmount": "21,486,232",
                "poolBalanceAfterdraw": "0",
            },
            {
                "lotteryDrawNum": "26312",
                "lotteryDrawResult": "1 1 2",
                "lotteryDrawTime": "2026-11-22",
                "lotterySaleAmount": "20,000,000",
                "poolBalanceAfterdraw": "0",
            },
            {
                "lotteryDrawNum": "26310",
                "lotteryDrawResult": "10 2 3",
                "lotteryDrawTime": "2026-11-20",
            },
            {
                "lotteryDrawNum": "26313",
                "lotteryDrawResult": "0 3 6",
                "lotteryDrawTime": "2026-11-23",
            },
        ]
    },
}

PL5_HTML = """
<table id="tablelist">
<tr><td>期号</td><td>中奖号码</td><td>总和</td><td>总销售额(元)</td><td>开奖日期</td></tr>
<tr class="t_tr1"><td class="t_tr1">26311</td><td class="cfont2">9 8 7 6 5</td><td class="cfont4">35</td><td class="t_tr1">1,000,000</td><td class="t_tr1">2026-11-21</td></tr>
<tr class="t_tr1"><td class="t_tr1">26313</td><td class="cfont2">0 3 6 6 7</td><td class="cfont4">22</td><td class="t_tr1">21,486,232</td><td class="t_tr1">2026-11-23</td></tr>
<tr class="t_tr1"><td class="t_tr1">26312</td><td class="cfont2">1 1 2 3 4</td><td class="cfont4">11</td><td class="t_tr1">20,000,000</td><td class="t_tr1">2026-11-22</td></tr>
<tr class="t_tr1"><td class="t_tr1">26310</td><td class="cfont2">10 3 6 6 7</td><td class="cfont4">22</td><td class="t_tr1">19,000,000</td><td class="t_tr1">2026-11-20</td></tr>
<tr class="t_tr1"><td class="t_tr1">26309</td><td class="cfont2">1 2 3 4 5</td><td class="cfont4">15</td><td class="t_tr1">18,000,000</td><td class="t_tr1">--</td></tr>
</table>
"""

QXC_DATA = {
    "success": True,
    "value": {
        "list": [
            {
                "lotteryDrawNum": "26134",
                "lotteryDrawResult": "1 1 1 1 1 1 1",
                "lotteryDrawTime": "2026-11-22",
                "lotterySaleAmount": "10,000,000",
                "poolBalanceAfterdraw": "50,000,000",
            },
            {
                "lotteryDrawNum": "26135",
                "lotteryDrawResult": "7 2 4 7 6 3 14",
                "lotteryDrawTime": "2026-11-24",
                "lotterySaleAmount": "12,000,000",
                "poolBalanceAfterdraw": "60,000,000",
            },
            {
                "lotteryDrawNum": "26133",
                "lotteryDrawResult": "7 2 4 7 6 3 15",
                "lotteryDrawTime": "2026-11-20",
            },
            {
                "lotteryDrawNum": "26132",
                "lotteryDrawResult": "7 2 4 7 6 14",
                "lotteryDrawTime": "2026-11-19",
            },
        ]
    },
}

PL3_HTML = """
<table id="tablelist">
<tr><td>期号</td><td>开奖号码</td><td>总和</td><td>销售额(元)</td><td>直选</td><td>组选3</td><td>开奖日期</td></tr>
<tr class="t_tr1"><!--<td>2</td>--><td class="t_tr1">26311</td><td class="cfont2">9 8 7</td><td class="cfont4">24</td><td class="t_tr1">1,000,000</td><td class="t_tr1">1040</td><td class="t_tr1">2026-11-21</td></tr>
<tr class="t_tr1"><!--<td>2</td>--><td class="t_tr1">26313</td><td class="cfont2">0 3 6</td><td class="cfont4">9</td><td class="t_tr1">41,632,870</td><td class="t_tr1">1,040</td><td class="t_tr1">2026-11-23</td></tr>
<tr class="t_tr1"><!--<td>2</td>--><td class="t_tr1">26312</td><td class="cfont2">1 1 2</td><td class="cfont4">4</td><td class="t_tr1">40,000,000</td><td class="t_tr1">346</td><td class="t_tr1">2026-11-22</td></tr>
<tr class="t_tr1"><!--<td>2</td>--><td class="t_tr1">26310</td><td class="cfont2">10 2 3</td><td class="cfont4">6</td><td class="t_tr1">39,000,000</td><td class="t_tr1">173</td><td class="t_tr1">2026-11-20</td></tr>
<tr class="t_tr1"><!--<td>2</td>--><td class="t_tr1">26309</td><td class="cfont2">1 2 3</td><td class="cfont4">6</td><td class="t_tr1">38,000,000</td><td class="t_tr1">173</td><td class="t_tr1">--</td></tr>
</table>
"""

QXC_HTML = """
<table id="tablelist">
<tr><td>期号</td><td>开奖号码</td><td>总和</td><td>销售额</td><td>开奖日期</td></tr>
<tr class="t_tr1"><!--<td>2</td>--><td class="t_tr1">26133</td><td class="cfont2">1 1 1 1 1 1 1<span class="cBlue"> </span></td><td>7</td><td class="t_tr1">9000000</td><td class="t_tr1">2026-11-21</td></tr>
<tr class="t_tr1"><!--<td>2</td>--><td class="t_tr1">26134</td><td class="cfont2">7 2 4 7 6 3 14<span class="cBlue"> </span></td><td>43</td><td class="t_tr1">13204226</td><td class="t_tr1">2026-11-22</td></tr>
<tr class="t_tr1"><!--<td>2</td>--><td class="t_tr1">26132</td><td class="cfont2">0 1 2 3 4 5 15<span class="cBlue"> </span></td><td>30</td><td class="t_tr1">8000000</td><td class="t_tr1">2026-11-19</td></tr>
</table>
"""


def boom(_url):
    raise RuntimeError("模拟数据源不可用")


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", str(tmp_path / "helper.db"))
    monkeypatch.setattr(cache, "CACHE_DIR", tmp_path / "cache")
    # 隔离 core.store，避免测试期间访问网络或写入项目数据。
    monkeypatch.setattr(core_store, "ensure_data", lambda: {"count": len(CORE_DRAWS)})
    monkeypatch.setattr(
        core_store, "get_draws", lambda: [dict(draw) for draw in CORE_DRAWS]
    )
    with TestClient(app) as test_client:
        yield test_client


# ---------- 通用 ----------


def test_source_names():
    assert dlt.SOURCE_NAME == "国家体彩中心 / 500.com"
    assert pl5.SOURCE_NAME == "国家体彩中心 / 500.com"
    assert pl3.SOURCE_NAME == "500.com / 国家体彩中心"
    assert qxc.SOURCE_NAME == "500.com / 国家体彩中心"


# ---------- 大乐透 ----------


def test_dlt_fetch_maps_core_draws(monkeypatch):
    monkeypatch.setattr(core_store, "ensure_data", lambda: {"count": 2})
    monkeypatch.setattr(
        core_store, "get_draws", lambda: [dict(draw) for draw in CORE_DRAWS]
    )

    draws = dlt.fetch_draws(limit=1)
    assert len(draws) == 1
    assert draws[0] == {
        "issue": "26135",
        "date": "2026-11-24",
        "numbers": {"front": [1, 2, 3, 4, 5], "back": [1, 2]},
        "extra": {"pool": 123456789},
    }


def test_dlt_fetch_raises_when_core_fails(monkeypatch):
    monkeypatch.setattr(
        core_store, "ensure_data", lambda: (_ for _ in ()).throw(RuntimeError("boom"))
    )
    with pytest.raises(dlt.DataFetchError):
        dlt.fetch_draws()

    monkeypatch.setattr(core_store, "ensure_data", lambda: {})
    monkeypatch.setattr(core_store, "get_draws", lambda: [])
    with pytest.raises(dlt.DataFetchError):
        dlt.fetch_draws()


def test_dlt_refresh_draws_updates_core_before_reading(monkeypatch):
    calls = []

    def fake_refresh():
        calls.append("refresh")
        return {"added": 1}

    monkeypatch.setattr(core_store, "refresh", fake_refresh)
    monkeypatch.setattr(core_store, "ensure_data", lambda: {})
    monkeypatch.setattr(
        core_store, "get_draws", lambda: [dict(draw) for draw in CORE_DRAWS]
    )

    draws = dlt.refresh_draws(limit=2)
    assert calls == ["refresh"]
    assert len(draws) == 2


def test_dlt_refresh_draws_falls_back_when_refresh_fails(monkeypatch):
    monkeypatch.setattr(
        core_store,
        "refresh",
        lambda: (_ for _ in ()).throw(RuntimeError("offline")),
    )
    monkeypatch.setattr(core_store, "ensure_data", lambda: {})
    monkeypatch.setattr(
        core_store, "get_draws", lambda: [dict(draw) for draw in CORE_DRAWS]
    )

    draws = dlt.refresh_draws(limit=1)
    assert len(draws) == 1


def test_dlt_reuses_core_rules():
    assert dlt.tier_for_hits is core_rules.tier_for_hits


def test_dlt_validate_normalizes_and_checks():
    result = dlt.validate_ticket("01 02 03 04 05 + 01 02")
    assert result["ok"] is True
    assert result["normalized"]["front"] == [1, 2, 3, 4, 5]
    assert result["normalized"]["back"] == [1, 2]

    additional = dlt.validate_ticket(
        {"front": [5, 4, 3, 2, 1], "back": [12, 11]}, "additional"
    )
    assert additional["ok"] is True
    assert additional["normalized"]["front"] == [1, 2, 3, 4, 5]
    assert additional["normalized"]["play_type"] == "additional"

    cases = [
        ({"front": [1, 2, 3, 4], "back": [1, 2]}, "前区需要 5 个号码"),
        ({"front": [1, 2, 3, 4, 36], "back": [1, 2]}, "前区号码范围应为 1-35"),
        ({"front": [1, 2, 3, 4, 4], "back": [1, 2]}, "前区号码不能重复"),
        ({"front": [1, 2, 3, 4, 5], "back": [1]}, "后区需要 2 个号码"),
        ({"front": [1, 2, 3, 4, 5], "back": [1, 13]}, "后区号码范围应为 1-12"),
        ({"front": [1, 2, 3, 4, 5], "back": [1, 1]}, "后区号码不能重复"),
        ("01 02 03 04 05 01", "需要前区 5 个号码和后区 2 个号码"),
        ({"front": "a b c d e", "back": [1, 2]}, "号码格式不正确"),
    ]
    for payload, expected in cases:
        checked = dlt.validate_ticket(payload)
        assert checked["ok"] is False
        assert expected in checked["errors"]


def test_dlt_check_tiers_and_messages():
    draw = {"numbers": {"front": [1, 2, 3, 4, 5], "back": [1, 2]}}

    first = dlt.check_ticket({"front": [1, 2, 3, 4, 5], "back": [1, 2]}, None, draw)
    assert first["ok"] is True and first["hit"] is True
    assert first["prize_level"] == "一等奖"
    assert first["detail"]["tier"] == 1
    assert "奖金以官方公告为准" in first["message"]

    fourth = dlt.check_ticket(
        {"front": [1, 2, 3, 4, 30], "back": [1, 3]}, None, draw
    )
    assert fourth["prize_level"] == "四等奖"
    assert fourth["detail"]["front_hits"] == 4
    assert fourth["detail"]["back_hits"] == 1

    sixth = dlt.check_ticket(
        {"front": [1, 2, 3, 30, 31], "back": [1, 3]}, None, draw
    )
    assert sixth["prize_level"] == "六等奖"

    miss = dlt.check_ticket(
        {"front": [10, 11, 12, 13, 14], "back": [3, 4]}, None, draw
    )
    assert miss["hit"] is False and miss["prize_level"] is None
    assert miss["detail"]["tier"] is None

    additional = dlt.check_ticket(
        {"front": [1, 2, 3, 4, 5], "back": [1, 2]}, "additional", draw
    )
    assert "追加奖金以官方规则为准" in additional["message"]

    invalid = dlt.check_ticket({"front": [1, 2], "back": [1, 2]}, None, draw)
    assert invalid["ok"] is False


# ---------- 排列3 ----------


def test_pl3_fetch_parses_500_html(monkeypatch):
    monkeypatch.setattr(
        pl3,
        "_request",
        lambda url: FakeResponse(content=PL3_HTML.encode("gb18030")),
    )

    draws = pl3.fetch_draws()
    assert [draw["issue"] for draw in draws] == ["26313", "26312", "26311"]
    assert draws[0]["numbers"] == {"digits": [0, 3, 6]}
    assert draws[0]["date"] == "2026-11-23"
    assert draws[0]["extra"]["sales"] == 41632870


def test_pl3_falls_back_to_sporttery(monkeypatch):
    def fake_request(url):
        if "500.com" in url:
            raise RuntimeError("主数据源不可用")
        return FakeResponse(payload=PL3_DATA)

    monkeypatch.setattr(pl3, "_request", fake_request)

    draws = pl3.fetch_draws()
    assert [draw["issue"] for draw in draws] == ["26313", "26312", "26311"]
    assert draws[0]["numbers"] == {"digits": [0, 3, 6]}
    assert draws[0]["date"] == "2026-11-23"
    assert draws[0]["extra"]["pool"] == 0


def test_pl3_fetch_raises_when_both_sources_fail(monkeypatch):
    monkeypatch.setattr(pl3, "_request", boom)
    with pytest.raises(pl3.DataFetchError):
        pl3.fetch_draws()

    def bad_fallback(url):
        if "500.com" in url:
            raise RuntimeError("主数据源不可用")
        return FakeResponse(payload={"success": False})

    monkeypatch.setattr(pl3, "_request", bad_fallback)
    with pytest.raises(pl3.DataFetchError):
        pl3.fetch_draws()


def test_pl3_validate_boundaries():
    assert pl3.validate_ticket("036")["ok"] is True
    assert pl3.validate_ticket("036")["normalized"]["digits"] == [0, 3, 6]
    assert pl3.validate_ticket({"digits": [0, 3, 6]}, "zhixuan")["ok"] is True
    assert pl3.validate_ticket({"digits": [1, 1, 2]}, "zu3")["ok"] is True
    assert pl3.validate_ticket({"digits": [3, 2, 1]}, "zu6")["ok"] is True

    cases = [
        ("03", None, "需要 3 个数字"),
        ("10 3 6", None, "号码范围应为 0-9"),
        ("a b c", None, "号码格式不正确"),
        ({"digits": [1, 2, 3]}, "zu3", "组选3 号码必须有两个数字相同"),
        ({"digits": [1, 1, 2]}, "zu6", "组选6 号码必须三个数字互不相同"),
        ({"digits": [0, 3, 6]}, "foo", "不支持的玩法"),
    ]
    for payload, play_type, expected in cases:
        checked = pl3.validate_ticket(payload, play_type)
        assert checked["ok"] is False
        assert expected in checked["errors"]


def test_pl3_check_all_play_types():
    direct_draw = {"numbers": {"digits": [0, 3, 6]}}
    direct = pl3.check_ticket({"digits": [0, 3, 6]}, "zhixuan", direct_draw)
    assert direct["hit"] is True
    assert direct["prize_level"] == "直选"
    assert direct["detail"]["prize_amount"] == 1040
    assert "固定奖金" in direct["message"] and "以官方公告为准" in direct["message"]

    direct_miss = pl3.check_ticket({"digits": [6, 3, 0]}, "zhixuan", direct_draw)
    assert direct_miss["hit"] is False

    zu3_draw = {"numbers": {"digits": [1, 1, 2]}}
    zu3 = pl3.check_ticket({"digits": [2, 1, 1]}, "zu3", zu3_draw)
    assert zu3["hit"] is True
    assert zu3["prize_level"] == "组选3"
    assert zu3["detail"]["prize_amount"] == 346

    zu3_miss = pl3.check_ticket({"digits": [1, 2, 2]}, "zu3", zu3_draw)
    assert zu3_miss["hit"] is False

    zu6_draw = {"numbers": {"digits": [1, 2, 3]}}
    zu6 = pl3.check_ticket({"digits": [3, 2, 1]}, "zu6", zu6_draw)
    assert zu6["hit"] is True
    assert zu6["prize_level"] == "组选6"
    assert zu6["detail"]["prize_amount"] == 173

    # 开奖号码不是三个互不相同，不能按组选6 中奖
    zu6_miss = pl3.check_ticket({"digits": [1, 2, 3]}, "zu6", zu3_draw)
    assert zu6_miss["hit"] is False

    invalid = pl3.check_ticket({"digits": [1, 2]}, "zhixuan", direct_draw)
    assert invalid["ok"] is False


# ---------- 排列5 ----------


def test_pl5_fetch_parses_html(monkeypatch):
    monkeypatch.setattr(
        pl5,
        "_request",
        lambda url: FakeResponse(content=PL5_HTML.encode("gb2312")),
    )

    draws = pl5.fetch_draws()
    assert [draw["issue"] for draw in draws] == ["26313", "26312", "26311"]
    assert draws[0]["numbers"] == {"digits": [0, 3, 6, 6, 7]}
    assert draws[0]["date"] == "2026-11-23"
    assert draws[0]["extra"]["sales"] == 21486232


def test_pl5_fetch_raises_on_bad_html(monkeypatch):
    monkeypatch.setattr(
        pl5, "_request", lambda url: FakeResponse(content="<html></html>".encode())
    )
    with pytest.raises(pl5.DataFetchError):
        pl5.fetch_draws()


def test_pl5_validate_and_check():
    assert pl5.validate_ticket("03667")["normalized"]["digits"] == [0, 3, 6, 6, 7]
    assert pl5.validate_ticket("0 3 6 6 7")["ok"] is True
    # 排列5 允许重复数字
    assert pl5.validate_ticket({"digits": [0, 3, 3, 6, 7]})["ok"] is True

    cases = [
        ("0366", "需要 5 个数字"),
        ("0 3 6 6 10", "号码范围应为 0-9"),
        ("0366a", "号码格式不正确"),
    ]
    for payload, expected in cases:
        checked = pl5.validate_ticket(payload)
        assert checked["ok"] is False
        assert expected in checked["errors"]

    draw = {"numbers": {"digits": [0, 3, 6, 6, 7]}}
    hit = pl5.check_ticket("03667", None, draw)
    assert hit["hit"] is True
    assert hit["prize_level"] == "一等奖"
    assert hit["detail"]["prize_amount"] == 100000
    assert "以官方公告为准" in hit["message"]

    miss = pl5.check_ticket("03668", None, draw)
    assert miss["hit"] is False and miss["prize_level"] is None

    invalid = pl5.check_ticket("0366", None, draw)
    assert invalid["ok"] is False


# ---------- 七星彩 ----------


def test_qxc_fetch_parses_500_html_and_skips_invalid(monkeypatch):
    monkeypatch.setattr(
        qxc,
        "_request",
        lambda url: FakeResponse(content=QXC_HTML.encode("gb18030")),
    )

    draws = qxc.fetch_draws()
    assert [draw["issue"] for draw in draws] == ["26134", "26133"]
    assert draws[0]["numbers"] == {"front": [7, 2, 4, 7, 6, 3], "back": 14}
    assert draws[0]["date"] == "2026-11-22"
    assert draws[0]["extra"]["sales"] == 13204226


def test_qxc_falls_back_to_sporttery(monkeypatch):
    def fake_request(url):
        if "500.com" in url:
            raise RuntimeError("主数据源不可用")
        return FakeResponse(payload=QXC_DATA)

    monkeypatch.setattr(qxc, "_request", fake_request)

    draws = qxc.fetch_draws()
    assert [draw["issue"] for draw in draws] == ["26135", "26134"]
    assert draws[0]["numbers"] == {"front": [7, 2, 4, 7, 6, 3], "back": 14}
    assert draws[0]["date"] == "2026-11-24"


def test_qxc_fetch_raises_when_both_sources_fail(monkeypatch):
    monkeypatch.setattr(qxc, "_request", boom)
    with pytest.raises(qxc.DataFetchError):
        qxc.fetch_draws()

    def bad_fallback(url):
        if "500.com" in url:
            raise RuntimeError("主数据源不可用")
        return FakeResponse(payload={"value": {"list": []}})

    monkeypatch.setattr(qxc, "_request", bad_fallback)
    with pytest.raises(qxc.DataFetchError):
        qxc.fetch_draws()


def test_qxc_validate_forms():
    expected = {"front": [7, 2, 4, 7, 6, 3], "back": 14}
    for payload in (
        {"front": [7, 2, 4, 7, 6, 3], "back": 14},
        "7 2 4 7 6 3 14",
        "72476314",
        "724763 14",
    ):
        result = qxc.validate_ticket(payload)
        assert result["ok"] is True, (payload, result)
        assert result["normalized"]["front"] == expected["front"]
        assert result["normalized"]["back"] == expected["back"]

    cases = [
        ({"front": [7, 2, 4, 7, 6], "back": 14}, "前区需要 6 位数字"),
        ({"front": [10, 2, 4, 7, 6, 3], "back": 14}, "前区号码范围应为 0-9"),
        ({"front": [7, 2, 4, 7, 6, 3], "back": 15}, "后区号码范围应为 0-14"),
        ({"front": [7, 2, 4, 7, 6, 3], "back": "abc"}, "后区号码格式不正确"),
        ("7 2 4 7 6 3 14 15", "需要前区 6 位数字和后区 1 位数字"),
    ]
    for payload, expected_error in cases:
        checked = qxc.validate_ticket(payload)
        assert checked["ok"] is False
        assert expected_error in checked["errors"], checked


def test_qxc_check_official_tiers():
    draw = {"numbers": {"front": [7, 2, 4, 7, 6, 3], "back": 14}}

    def result(front, back):
        return qxc.check_ticket({"front": front, "back": back}, None, draw)

    tiers = [
        ([7, 2, 4, 7, 6, 3], 14, "一等奖", 1),
        ([7, 2, 4, 7, 6, 3], 13, "二等奖", 2),
        ([7, 2, 4, 7, 6, 9], 14, "三等奖", 3),
        ([7, 2, 4, 7, 6, 9], 13, "四等奖", 4),
        ([7, 2, 4, 7, 9, 9], 14, "四等奖", 4),
        ([7, 2, 4, 7, 9, 9], 13, "五等奖", 5),
        ([7, 2, 4, 9, 9, 9], 14, "五等奖", 5),
        ([7, 2, 4, 9, 9, 9], 13, "六等奖", 6),
        ([7, 2, 9, 9, 9, 9], 14, "六等奖", 6),
        ([7, 9, 9, 9, 9, 9], 14, "六等奖", 6),
        ([9, 9, 9, 9, 9, 9], 14, "六等奖", 6),
    ]
    for front, back, label, tier in tiers:
        checked = result(front, back)
        assert checked["hit"] is True, (front, back)
        assert checked["prize_level"] == label, (front, back, checked)
        assert checked["detail"]["tier"] == tier

    miss = result([7, 2, 9, 9, 9, 9], 13)
    assert miss["hit"] is False and miss["prize_level"] is None
    assert miss["detail"]["tier"] is None

    for checked in (
        result([7, 2, 4, 7, 6, 3], 14),
        result([7, 2, 4, 7, 6, 9], 13),
    ):
        assert "以官方公告为准" in checked["message"]


# ---------- API 端到端与缓存 ----------


def test_api_pl3_draws_cache_then_check(client, monkeypatch):
    monkeypatch.setattr(
        pl3,
        "_request",
        lambda url: FakeResponse(content=PL3_HTML.encode("gb18030")),
    )

    resp = client.get("/api/helper/games/pl3/draws")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["source"] == pl3.SOURCE_NAME
    assert body["draws"][0]["issue"] == "26313"
    assert cache.cache_path("pl3").exists()

    checked = client.post(
        "/api/helper/check",
        json={
            "game_code": "pl3",
            "play_type": "zhixuan",
            "payload": {"digits": [0, 3, 6]},
        },
    )
    assert checked.status_code == 200
    result = checked.json()["result"]
    assert result["hit"] is True
    assert result["prize_level"] == "直选"


def test_api_dlt_draws_from_core_then_check(client):
    resp = client.get("/api/helper/games/dlt/draws")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["draws"][0]["issue"] == "26135"
    assert body["draws"][0]["numbers"] == {"front": [1, 2, 3, 4, 5], "back": [1, 2]}

    checked = client.post(
        "/api/helper/check",
        json={
            "game_code": "dlt",
            "play_type": None,
            "payload": {"front": [1, 2, 3, 4, 5], "back": [1, 2]},
        },
    )
    assert checked.status_code == 200
    result = checked.json()["result"]
    assert result["hit"] is True
    assert result["prize_level"] == "一等奖"
    assert result["detail"]["tier"] == 1


def test_refresh_both_sources_fail_keeps_old_cache(client, monkeypatch):
    monkeypatch.setattr(
        pl3,
        "_request",
        lambda url: FakeResponse(content=PL3_HTML.encode("gb18030")),
    )
    assert client.get("/api/helper/games/pl3/draws").json()["status"] == "ok"

    before = cache.load_cache("pl3")
    assert before["draws"]

    monkeypatch.setattr(pl3, "_request", boom)
    resp = client.post("/api/helper/games/pl3/refresh")
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is False
    assert body["status"] == "stale"
    assert body["latest_issue"] == "26313"

    after = cache.load_cache("pl3")
    assert after["source"] == before["source"]
    assert after["updated_at"] == before["updated_at"]
    assert [draw["issue"] for draw in after["draws"]] == [
        draw["issue"] for draw in before["draws"]
    ]
