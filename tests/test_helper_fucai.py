"""福彩数字型（双色球、福彩3D、七乐彩、快乐8）适配器与 API 测试。

所有网络请求均通过 monkeypatch 模块内的 `_request_json` 隔离，测试不联网。
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from helper import config
from helper.games import cache, fc3d, kl8, qlc, ssq
from helper_app import app

# ---------- 真实接口结构 fixture ----------

SSQ_RESPONSE = {
    "state": 0,
    "message": "查询成功",
    "result": [
        {
            "name": "双色球",
            "code": "2026133",
            "date": "2026-11-19(四)",
            "week": "四",
            "red": "07,10,11,14,21,26",
            "blue": "13",
        },
        {
            "name": "双色球",
            "code": "2026134",
            "date": "2026-11-22(日)",
            "week": "日",
            "red": "04,05,10,17,21,32",
            "blue": "08",
        },
    ],
}

FC3D_RESPONSE = {
    "state": 0,
    "message": "查询成功",
    "result": [
        {
            "name": "3D",
            "code": "2026313",
            "date": "2026-11-23(一)",
            "week": "一",
            "red": "3,4,6",
            "blue": "",
        }
    ],
}

QLC_RESPONSE = {
    "state": 0,
    "message": "查询成功",
    "result": [
        {
            "name": "七乐彩",
            "code": "2026135",
            "date": "2026-11-23(一)",
            "week": "一",
            "red": "01,02,07,10,12,21,26",
            "blue": "03",
        }
    ],
}

KL8_RESPONSE = {
    "state": 0,
    "message": "查询成功",
    "result": [
        {
            "name": "快乐8",
            "code": "2026313",
            "date": "2026-11-23(一)",
            "week": "一",
            "red": (
                "03,19,20,22,25,27,28,35,36,40,"
                "50,52,53,56,57,64,67,69,75,77"
            ),
            "blue": "",
        }
    ],
}


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", str(tmp_path / "helper.db"))
    monkeypatch.setattr(cache, "CACHE_DIR", tmp_path / "cache")
    with TestClient(app) as test_client:
        yield test_client


# ---------- 开奖数据抓取解析 ----------


def test_ssq_fetch_parses_and_sorts_desc(monkeypatch):
    monkeypatch.setattr(ssq, "_request_json", lambda url: SSQ_RESPONSE)
    draws = ssq.fetch_draws(limit=30)

    assert [draw["issue"] for draw in draws] == ["2026134", "2026133"]
    assert draws[0]["date"] == "2026-11-22"
    assert draws[0]["numbers"] == {"red": [4, 5, 10, 17, 21, 32], "blue": [8]}
    assert all(isinstance(draw["issue"], str) for draw in draws)


def test_fc3d_fetch_parses_digits(monkeypatch):
    monkeypatch.setattr(fc3d, "_request_json", lambda url: FC3D_RESPONSE)
    draws = fc3d.fetch_draws(limit=30)

    assert draws[0]["issue"] == "2026313"
    assert draws[0]["numbers"] == {"digits": [3, 4, 6]}


def test_qlc_fetch_parses_basic_and_special(monkeypatch):
    monkeypatch.setattr(qlc, "_request_json", lambda url: QLC_RESPONSE)
    draws = qlc.fetch_draws(limit=30)

    assert draws[0]["numbers"] == {
        "basic": [1, 2, 7, 10, 12, 21, 26],
        "special": 3,
    }


def test_kl8_fetch_parses_twenty_numbers(monkeypatch):
    monkeypatch.setattr(kl8, "_request_json", lambda url: KL8_RESPONSE)
    draws = kl8.fetch_draws(limit=30)

    numbers = draws[0]["numbers"]["draw"]
    assert len(numbers) == 20
    assert numbers == sorted(numbers)
    assert numbers[:3] == [3, 19, 20]


def test_fetch_rejects_incomplete_records(monkeypatch):
    broken = {
        "state": 0,
        "result": [
            {"code": "2026999", "date": "2026-01-01(四)", "red": "04,05", "blue": "08"}
        ],
    }
    monkeypatch.setattr(ssq, "_request_json", lambda url: broken)
    with pytest.raises(ValueError):
        ssq.fetch_draws()

    empty_blue = {
        "state": 0,
        "result": [
            {
                "code": "2026999",
                "date": "2026-01-01(四)",
                "red": "04,05,10,17,21,32",
                "blue": "",
            }
        ],
    }
    monkeypatch.setattr(ssq, "_request_json", lambda url: empty_blue)
    with pytest.raises(ValueError):
        ssq.fetch_draws()


def test_fetch_rejects_error_state(monkeypatch):
    monkeypatch.setattr(ssq, "_request_json", lambda url: {"state": 1, "result": []})
    with pytest.raises(ValueError):
        ssq.fetch_draws()


# ---------- 双色球校验与核对 ----------


def test_ssq_validate_accepts_dict_and_text():
    assert ssq.validate_ticket(
        {"red": [1, 2, 3, 4, 5, 6], "blue": [7]}
    )["ok"] is True
    assert ssq.validate_ticket(
        {"red": [6, 5, 4, 3, 2, 1], "blue": 16}
    )["normalized"] == {"red": [1, 2, 3, 4, 5, 6], "blue": [16]}
    assert ssq.validate_ticket("01 02 03 04 05 06 + 07")["ok"] is True


def test_ssq_validate_boundaries():
    duplicate = ssq.validate_ticket({"red": [1, 2, 3, 4, 5, 5], "blue": [1]})
    assert duplicate["ok"] is False
    assert any("重复" in error for error in duplicate["errors"])

    out_of_range = ssq.validate_ticket({"red": [1, 2, 3, 4, 5, 34], "blue": [1]})
    assert out_of_range["ok"] is False
    assert any("1-33" in error for error in out_of_range["errors"])

    bad_blue = ssq.validate_ticket({"red": [1, 2, 3, 4, 5, 6], "blue": [17]})
    assert bad_blue["ok"] is False
    assert any("蓝球" in error for error in bad_blue["errors"])

    wrong_count = ssq.validate_ticket({"red": [1, 2, 3], "blue": [1]})
    assert wrong_count["ok"] is False


@pytest.mark.parametrize(
    ("red", "blue", "expected_level"),
    [
        ([4, 5, 10, 17, 21, 32], 8, "一等奖"),
        ([4, 5, 10, 17, 21, 32], 9, "二等奖"),
        ([4, 5, 10, 17, 21, 30], 8, "三等奖"),
        ([4, 5, 10, 17, 21, 30], 9, "四等奖"),
        ([4, 5, 10, 17, 20, 30], 8, "四等奖"),
        ([4, 5, 10, 17, 20, 30], 9, "五等奖"),
        ([4, 5, 10, 16, 20, 30], 8, "五等奖"),
        ([4, 5, 9, 16, 20, 30], 8, "六等奖"),
        ([4, 8, 9, 16, 20, 30], 8, "六等奖"),
        ([11, 12, 13, 14, 15, 16], 8, "六等奖"),
        ([4, 5, 10, 16, 20, 30], 9, None),
    ],
)
def test_ssq_check_prize_levels(red, blue, expected_level):
    draw = {
        "issue": "2026134",
        "date": "2026-11-22",
        "numbers": {"red": [4, 5, 10, 17, 21, 32], "blue": [8]},
    }
    result = ssq.check_ticket({"red": red, "blue": [blue]}, None, draw)

    assert result["ok"] is True
    assert result["prize_level"] == expected_level
    assert result["hit"] is (expected_level is not None)
    assert result["detail"]["red_hits"] == len(set(red) & {4, 5, 10, 17, 21, 32})
    assert result["detail"]["blue_hit"] is (blue == 8)
    assert "以官方公告为准" in result["message"]


def test_ssq_check_rejects_invalid_ticket():
    draw = {
        "issue": "2026134",
        "date": "2026-11-22",
        "numbers": {"red": [4, 5, 10, 17, 21, 32], "blue": [8]},
    }
    result = ssq.check_ticket({"red": [1, 2, 3], "blue": [8]}, None, draw)
    assert result["ok"] is False
    assert result["hit"] is False
    assert result["detail"]["errors"]


# ---------- 福彩3D校验与核对 ----------


def test_fc3d_validate_play_types():
    assert fc3d.validate_ticket({"digits": [3, 4, 6]})["normalized"] == {
        "digits": [3, 4, 6],
        "play_type": "zhixuan",
    }
    assert fc3d.validate_ticket({"digits": "346"})["ok"] is True
    assert fc3d.validate_ticket({"digits": [1, 1, 2]}, "zu3")["ok"] is True
    assert fc3d.validate_ticket({"digits": [1, 2, 3]}, "组选6")["ok"] is True

    assert fc3d.validate_ticket({"digits": [1, 2, 3]}, "zu3")["ok"] is False
    assert fc3d.validate_ticket({"digits": [1, 1, 2]}, "zu6")["ok"] is False
    assert fc3d.validate_ticket({"digits": [1, 2, 10]})["ok"] is False
    assert fc3d.validate_ticket({"digits": [1, 2]})["ok"] is False


def test_fc3d_check_zhixuan_and_group():
    draw = {"issue": "2026313", "date": "2026-11-23", "numbers": {"digits": [3, 4, 6]}}

    direct = fc3d.check_ticket({"digits": [3, 4, 6]}, "zhixuan", draw)
    assert direct["hit"] is True
    assert direct["prize_level"] == "直选"
    assert "1040" in direct["message"]

    wrong_order = fc3d.check_ticket({"digits": [6, 4, 3]}, "zhixuan", draw)
    assert wrong_order["hit"] is False

    zu6 = fc3d.check_ticket({"digits": [6, 3, 4]}, "zu6", draw)
    assert zu6["hit"] is True
    assert zu6["prize_level"] == "组选6"

    zu3_mismatch = fc3d.check_ticket({"digits": [1, 1, 2]}, "zu3", draw)
    assert zu3_mismatch["hit"] is False


def test_fc3d_check_zu3_requires_repeat_in_draw():
    draw = {"issue": "2026314", "date": "2026-11-24", "numbers": {"digits": [1, 1, 2]}}
    result = fc3d.check_ticket({"digits": [1, 2, 1]}, "zu3", draw)
    assert result["hit"] is True
    assert result["prize_level"] == "组选3"
    assert "346" in result["message"]

    draw_distinct = {
        "issue": "2026314",
        "date": "2026-11-24",
        "numbers": {"digits": [1, 2, 3]},
    }
    assert fc3d.check_ticket({"digits": [1, 1, 2]}, "zu3", draw_distinct)["hit"] is False


# ---------- 七乐彩校验与核对 ----------


def test_qlc_validate_boundaries():
    assert qlc.validate_ticket({"basic": [1, 2, 3, 4, 5, 6, 7]})["ok"] is True
    assert qlc.validate_ticket("01 02 03 04 05 06 07")["ok"] is True
    assert qlc.validate_ticket({"basic": [1, 2, 3, 4, 5, 6, 6]})["ok"] is False
    assert qlc.validate_ticket({"basic": [1, 2, 3, 4, 5, 6, 31]})["ok"] is False
    assert qlc.validate_ticket({"basic": [1, 2, 3]})["ok"] is False


def test_qlc_check_all_levels():
    draw = {
        "issue": "2026135",
        "date": "2026-11-23",
        "numbers": {"basic": [1, 2, 3, 4, 5, 6, 7], "special": 8},
    }
    cases = [
        ([1, 2, 3, 4, 5, 6, 7], "一等奖", None, False),
        ([1, 2, 3, 4, 5, 6, 8], "二等奖", None, True),
        ([1, 2, 3, 4, 5, 6, 9], "三等奖", None, False),
        ([1, 2, 3, 4, 5, 8, 9], "四等奖", 200, True),
        ([1, 2, 3, 4, 5, 9, 10], "五等奖", 50, False),
        ([1, 2, 3, 4, 8, 9, 10], "六等奖", 10, True),
        ([1, 2, 3, 4, 9, 10, 11], "七等奖", 5, False),
        ([1, 2, 3, 9, 10, 11, 12], None, None, False),
    ]
    for basic, level, amount, special_hit in cases:
        result = qlc.check_ticket({"basic": basic}, None, draw)
        assert result["ok"] is True
        assert result["prize_level"] == level
        assert result["detail"]["basic_hits"] == len(set(basic) & set(range(1, 8)))
        assert result["detail"]["special_hit"] is special_hit
        assert result["detail"]["prize_amount"] == amount

    assert "以官方公告为准" in qlc.check_ticket({"basic": [1, 2, 3, 4, 5, 6, 7]}, None, draw)["message"]


# ---------- 快乐8校验与核对 ----------


def test_kl8_validate_play_types():
    inferred = kl8.validate_ticket({"picks": [1, 5, 10]})
    assert inferred["ok"] is True
    assert inferred["normalized"]["play_type"] == "select3"
    assert inferred["normalized"]["pick_count"] == 3

    assert kl8.validate_ticket({"picks": list(range(1, 9))}, "select8")["ok"] is True

    mismatch = kl8.validate_ticket({"picks": list(range(1, 9))}, "select7")
    assert mismatch["ok"] is False
    assert any("不一致" in error for error in mismatch["errors"])

    assert kl8.validate_ticket({"picks": [1, 1, 2]})["ok"] is False
    assert kl8.validate_ticket({"picks": [0, 2]})["ok"] is False
    assert kl8.validate_ticket({"picks": []})["ok"] is False
    assert kl8.validate_ticket({"picks": list(range(1, 12))})["ok"] is False


@pytest.mark.parametrize(
    ("pick_count", "hits"),
    sorted(
        (pick_count, hits)
        for pick_count, table in kl8._PRIZE_TABLE.items()
        for hits in table
    ),
)
def test_kl8_full_prize_table(pick_count, hits):
    draw = {
        "issue": "2026313",
        "date": "2026-11-23",
        "numbers": {"draw": list(range(1, 21))},
    }
    picks = list(range(1, hits + 1)) + [
        number
        for number in range(21, 41)
        if len(range(1, hits + 1)) + (number - 20) <= pick_count
    ]
    assert len(picks) == pick_count

    result = kl8.check_ticket({"picks": picks}, f"select{pick_count}", draw)
    assert result["hit"] is True
    assert result["detail"]["hits"] == hits
    assert result["detail"]["pick_count"] == pick_count
    assert result["detail"]["prize_amount"] == kl8._PRIZE_TABLE[pick_count][hits]
    assert result["prize_level"] == (
        "选" + kl8._CN_NUMBERS[pick_count] + "中" + kl8._CN_NUMBERS[hits]
    )


def test_kl8_check_prize_tiers():
    draw = {
        "issue": "2026313",
        "date": "2026-11-23",
        "numbers": {"draw": list(range(1, 21))},
    }

    top = kl8.check_ticket({"picks": list(range(1, 11))}, None, draw)
    assert top["prize_level"] == "选十中十"
    assert top["detail"]["hits"] == 10
    assert top["detail"]["pick_count"] == 10
    assert top["detail"]["prize_amount"] == 5000000
    assert "500 万" in top["message"]

    second = kl8.check_ticket({"picks": list(range(1, 10)) + [21]}, None, draw)
    assert second["prize_level"] == "选十中九"
    assert second["detail"]["prize_amount"] == 8000

    zero = kl8.check_ticket({"picks": list(range(21, 31))}, "select10", draw)
    assert zero["prize_level"] == "选十中零"
    assert zero["detail"]["prize_amount"] == 2

    eight = kl8.check_ticket({"picks": list(range(1, 9))}, "select8", draw)
    assert eight["prize_level"] == "选八中八"
    assert eight["detail"]["prize_amount"] == 50000

    seven = kl8.check_ticket({"picks": list(range(1, 8))}, None, draw)
    assert seven["prize_level"] == "选七中七"
    assert seven["detail"]["prize_amount"] == 8500

    single = kl8.check_ticket({"picks": [1]}, "select1", draw)
    assert single["prize_level"] == "选一中一"
    assert single["detail"]["prize_amount"] == 4.5

    missed = kl8.check_ticket({"picks": [1, 2, 3, 21, 22, 23, 24]}, None, draw)
    assert missed["hit"] is False
    assert missed["prize_level"] is None
    assert missed["detail"]["hits"] == 3


# ---------- API 端到端 ----------


def test_ssq_draws_api_end_to_end(client, monkeypatch):
    monkeypatch.setattr(ssq, "_request_json", lambda url: SSQ_RESPONSE)

    resp = client.get("/api/helper/games/ssq/draws")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["source"] == "中国福利彩票官网"
    assert [draw["issue"] for draw in body["draws"]] == ["2026134", "2026133"]
    assert body["draws"][0]["numbers"]["blue"] == [8]

    cached = cache.load_cache("ssq")
    assert cached["source"] == "中国福利彩票官网"
    assert cached["draws"][0]["issue"] == "2026134"


def test_check_api_end_to_end(client):
    draw = {
        "issue": "2026134",
        "date": "2026-11-22",
        "numbers": {"red": [4, 5, 10, 17, 21, 32], "blue": [8]},
        "extra": {},
    }
    assert cache.save_cache("ssq", [draw], "测试源") is not None

    resp = client.post(
        "/api/helper/check",
        json={
            "game_code": "ssq",
            "play_type": None,
            "payload": {"red": [4, 5, 10, 17, 21, 32], "blue": [8]},
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["game_code"] == "ssq"
    assert body["draw"] == {"issue": "2026134", "date": "2026-11-22"}
    assert body["result"]["hit"] is True
    assert body["result"]["prize_level"] == "一等奖"
    assert body["result"]["detail"]["red_hits"] == 6
    assert body["result"]["detail"]["blue_hit"] is True


def test_refresh_failure_keeps_old_cache(client, monkeypatch):
    old = {
        "issue": "2026133",
        "date": "2026-11-19",
        "numbers": {"red": [7, 10, 11, 14, 21, 26], "blue": [13]},
        "extra": {},
    }
    assert cache.save_cache("ssq", [old], "旧缓存") is not None
    before = cache.load_cache("ssq")

    def boom(url):
        raise RuntimeError("模拟数据源不可用")

    monkeypatch.setattr(ssq, "_request_json", boom)

    resp = client.post("/api/helper/games/ssq/refresh")
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is False
    assert body["status"] == "stale"
    assert body["latest_issue"] == "2026133"

    after = cache.load_cache("ssq")
    assert after["source"] == "旧缓存"
    assert after["updated_at"] == before["updated_at"]
    assert [draw["issue"] for draw in after["draws"]] == ["2026133"]

    fallback = client.get("/api/helper/games/ssq/draws", params={"refresh": "true"})
    assert fallback.status_code == 200
    assert fallback.json()["status"] == "stale"
    assert [draw["issue"] for draw in fallback.json()["draws"]] == ["2026133"]
