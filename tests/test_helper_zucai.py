"""足彩四种玩法适配器与 API 测试（网络全部 mock）。"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from helper import config
from helper.api import games as games_api
from helper.games import bqc6, cache, jq4, rx9, sfc14
from helper_app import app

SFC_RESULTS = ["3", "3", "3", "1", "0", "3", "1", "3", "3", "3", "0", "3", "1", "0"]
JQ4_TEAM_RESULTS = ["3", "0", "3", "0", "1", "1", "3", "1"]
JQ4_BUCKETS = ["3+", "3+", "2", "3+"]
JQ4_SCORES = ["4:0", "3:0", "1:1", "3:1"]
ZC6_PAIRS = [("3", "3"), ("3", "3"), ("1", "1"), ("1", "0"), ("3", "3"), ("3", "3")]
ZC6_SCORES = [("2:0", "4:0"), ("1:0", "3:0"), ("0:0", "1:1"), ("1:1", "2:3"), ("1:0", "3:1"), ("2:1", "3:2")]


# ---------------------------------------------------------------------------
# 精简 fixture：保持 500.com 期次表格的关键结构
# ---------------------------------------------------------------------------


def _sfc_page(results=None, issue="26168", date="2026年11月23日", history=()):
    results = results or SFC_RESULTS
    links = "".join(
        f'<a href="https://kaijiang.500.com/shtml/sfc/{item}.shtml">{item}</a>'
        for item in history
    )
    teams = "".join(
        f'<td width="34" class="div_shupai" title="主队{index}&nbsp;VS&nbsp;客队{index}">主队{index}</td>'
        for index in range(1, 15)
    )
    cells = "".join(
        f'<td><span class="cfont5 ">{value}</span></td>' for value in results
    )
    return (
        '<html><body><div class="iSelectList">'
        f"{links}</div>"
        '<table width="100%" class="kj_tablelist02">'
        '<tr><td colspan="14" class="td_title01">'
        '<span class="span_left"><a href="/shtml/sfc/'
        f'{issue}.shtml">胜负彩(任九) 第 <font class="cfont2"><strong>{issue}</strong>'
        '</font> 期</a></span>'
        f'<span class="span_right">开奖日期：{date} 兑奖截止日期：2027年1月21日</span>'
        "</td></tr>"
        f'<tr align="center">{teams}</tr>'
        f'<tr align="center">{cells}</tr>'
        "</table></body></html>"
    )


def _jq4_page(team_results=None, issue="26243", date="2026年11月24日"):
    team_results = team_results or JQ4_TEAM_RESULTS
    teams = "".join(
        f'<td width="61" class="div_shupai" title="主队{position // 2 + 1}VS客队{position // 2 + 1}">队{position + 1}</td>'
        for position in range(8)
    )
    cells = "".join(
        f'<td><span class="cfont5 ">{value}</span></td>' for value in team_results
    )
    return (
        '<html><body><table width="100%" class="kj_tablelist02">'
        '<tr><td colspan="8" class="td_title01">'
        f'<span class="span_left"><a href="/shtml/jq4/{issue}.shtml">进球彩 第 '
        f'<font class="cfont2"><strong>{issue}</strong></font> 期</a></span>'
        f'<span class="span_right">开奖日期：{date} 兑奖截止日期：2027年1月22日</span>'
        "</td></tr>"
        f'<tr align="center">{teams}</tr>'
        f'<tr align="center">{cells}</tr>'
        "</table></body></html>"
    )


def _zc6_page(pairs=None, issue="26236", date="2026年11月24日"):
    pairs = pairs or ZC6_PAIRS
    teams = "".join(
        f'<td class="div_shupai" colspan="2" title="主队{index}&nbsp;VS&nbsp;客队{index}">主队{index}</td>'
        for index in range(1, 7)
    )
    tokens = [value for pair in pairs for value in pair]
    cells = "".join(
        f'<td><span class="cfont5 ">{value}</span></td>' for value in tokens
    )
    return (
        '<html><body><table width="100%" class="kj_tablelist02">'
        '<tr><td colspan="12" class="td_title01">'
        f'<span class="span_left"><a href="/shtml/zc6/{issue}.shtml">半全场 第 '
        f'<font class="cfont2"><strong>{issue}</strong></font> 期</a></span>'
        f'<span class="span_right">开奖日期：{date} 兑奖截止日期：2027年1月22日</span>'
        "</td></tr>"
        f'<tr align="center">{teams}</tr>'
        f'<tr align="center">{cells}</tr>'
        "</table></body></html>"
    )


def _sfc_xml(results=None, issue="26168", date="2026-11-23", scores=None):
    results = results or SFC_RESULTS
    scores = scores or ["1:0"] * 14
    entries = "".join(
        f'<MatchTeam HomeTeamName="主队{index}" GuestTeamName="客队{index}" '
        f'MatchScore="{scores[index - 1]}" Result="{results[index - 1]}" '
        f'OrderNum="{index}" />'
        for index in range(1, 15)
    )
    return (
        f"<xml><PeriodicalNO>{issue}</PeriodicalNO>"
        f"<ResultTime>{date} 00:00:00</ResultTime>"
        f"<MatchTeams>{entries}</MatchTeams></xml>"
    )


def _jq4_xml(scores=None, issue="26243", date="2026-11-24"):
    scores = scores or JQ4_SCORES
    entries = ""
    for index, score in enumerate(scores):
        home_goals, away_goals = score.split(":")
        fixture = 1000 + index
        entries += (
            f'<MatchTeam TeamName="主队{index + 1}" MatchScore="{home_goals}" '
            f'Result="{_team_bucket(home_goals)}" OrderNum="{index * 2 + 1}" '
            f'FixtureID="{fixture}" />'
            f'<MatchTeam TeamName="客队{index + 1}" MatchScore="{away_goals}" '
            f'Result="{_team_bucket(away_goals)}" OrderNum="{index * 2 + 2}" '
            f'FixtureID="{fixture}" />'
        )
    return (
        f"<xml><PeriodicalNO>{issue}</PeriodicalNO>"
        f"<ResultTime>{date} 00:00:00</ResultTime>"
        f"<MatchTeams>{entries}</MatchTeams></xml>"
    )


def _zc6_xml(pairs=None, scores=None, issue="26236", date="2026-11-24"):
    pairs = pairs or ZC6_PAIRS
    scores = scores or ZC6_SCORES
    entries = "".join(
        f'<MatchTeam HomeTeamName="主队{index + 1}" GuestTeamName="客队{index + 1}" '
        f"HalfResult=\"{half}\" Result=\"{full}\" "
        f'HalfMatchScore="{scores[index][0]}" MatchScore="{scores[index][1]}" '
        f'OrderNum="{index + 1}" />'
        for index, (half, full) in enumerate(pairs)
    )
    return (
        f"<xml><PeriodicalNO>{issue}</PeriodicalNO>"
        f"<ResultTime>{date} 00:00:00</ResultTime>"
        f"<MatchTeams>{entries}</MatchTeams></xml>"
    )


def _team_bucket(goals) -> str:
    return "3+" if int(goals) >= 3 else str(goals)


def _fetcher(pages=None, xmls=None):
    pages = pages or {}
    xmls = xmls or {}

    def fetch(url: str, encoding: str = "gb18030") -> str:
        if "/xml/" in url:
            for issue, text in xmls.items():
                if url.endswith(f"/{issue}.xml"):
                    return text
            raise RuntimeError("期次明细不可用")
        for page_url, text in pages.items():
            if url == page_url:
                return text
        raise RuntimeError("页面不可用")

    return fetch


def _picks(results):
    return [{"index": index + 1, "pick": value} for index, value in enumerate(results)]


def _sfc_draw(results=None, issue="26168", date="2026-11-23"):
    results = results or SFC_RESULTS
    matches = [
        {
            "index": index + 1,
            "home": f"主队{index + 1}",
            "away": f"客队{index + 1}",
            "score": "1:0",
            "half_score": None,
            "result": value,
            "half_result": None,
        }
        for index, value in enumerate(results)
    ]
    return {"issue": issue, "date": date, "numbers": {}, "matches": matches, "extra": {}}


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", str(tmp_path / "helper.db"))
    monkeypatch.setattr(cache, "CACHE_DIR", tmp_path / "cache")
    with TestClient(app) as test_client:
        yield test_client


# ---------------------------------------------------------------------------
# 胜负彩14场
# ---------------------------------------------------------------------------


def test_sfc14_fetch_latest_with_xml_scores(monkeypatch):
    monkeypatch.setattr(
        sfc14,
        "_fetch_text",
        _fetcher(
            {sfc14.LATEST_URL: _sfc_page()},
            {"26168": _sfc_xml(scores=["4:0"] + ["1:0"] * 13)},
        ),
    )

    draws = sfc14.fetch_draws(limit=1)

    assert len(draws) == 1
    draw = draws[0]
    assert draw["issue"] == "26168"
    assert draw["date"] == "2026-11-23"
    assert draw["numbers"] == {}
    assert len(draw["matches"]) == 14
    assert [match["result"] for match in draw["matches"]] == SFC_RESULTS
    assert draw["matches"][0] == {
        "index": 1,
        "home": "主队1",
        "away": "客队1",
        "score": "4:0",
        "half_score": None,
        "result": "3",
        "half_result": None,
    }
    assert draw["extra"]["incomplete"] is False
    assert "奖金" in draw["extra"]["prize_note"]
    json.dumps(draws, ensure_ascii=False)


def test_sfc14_fetch_history_page_fallback(monkeypatch):
    pages = {
        sfc14.LATEST_URL: _sfc_page(history=("26167",)),
        sfc14.HISTORY_URL.format(issue="26167"): _sfc_page(
            issue="26167", date="2026年11月22日"
        ),
    }
    monkeypatch.setattr(sfc14, "_fetch_text", _fetcher(pages, {}))

    draws = sfc14.fetch_draws(limit=5)

    assert [draw["issue"] for draw in draws] == ["26168", "26167"]
    assert draws[1]["date"] == "2026-11-22"
    assert len(draws[1]["matches"]) == 14


def test_sfc14_fetch_broken_page_raises(monkeypatch):
    monkeypatch.setattr(
        sfc14,
        "_fetch_text",
        _fetcher({sfc14.LATEST_URL: "<html><body>暂无数据</body></html>"}),
    )
    with pytest.raises(ValueError):
        sfc14.fetch_draws(limit=1)


def test_sfc14_validate_boundaries():
    assert sfc14.validate_ticket({"picks": _picks(SFC_RESULTS)})["ok"] is True
    assert sfc14.validate_ticket("".join(SFC_RESULTS))["ok"] is True
    assert sfc14.validate_ticket("/".join(SFC_RESULTS))["ok"] is True

    missing = sfc14.validate_ticket({"picks": _picks(SFC_RESULTS[:13])})
    assert missing["ok"] is False
    assert any("14" in error for error in missing["errors"])

    duplicated = _picks(SFC_RESULTS)
    duplicated[13]["index"] = 13
    assert sfc14.validate_ticket({"picks": duplicated})["ok"] is False

    invalid = _picks(SFC_RESULTS)
    invalid[0]["pick"] = "2"
    result = sfc14.validate_ticket({"picks": invalid})
    assert result["ok"] is False
    assert any("3/1/0" in error for error in result["errors"])


def test_sfc14_check_prize_levels():
    draw = _sfc_draw()

    first = sfc14.check_ticket({"picks": _picks(SFC_RESULTS)}, None, draw)
    assert first["ok"] is True and first["hit"] is True
    assert first["prize_level"] == "一等奖"
    assert first["detail"]["hits"] == 14
    assert first["detail"]["wrong_indexes"] == []
    assert "官方公告" in first["message"]

    second_picks = _picks(SFC_RESULTS)
    second_picks[-1]["pick"] = "3"
    second = sfc14.check_ticket({"picks": second_picks}, None, draw)
    assert second["hit"] is True
    assert second["prize_level"] == "二等奖"
    assert second["detail"]["hits"] == 13
    assert second["detail"]["wrong_indexes"] == [14]

    third_picks = _picks(SFC_RESULTS)
    third_picks[-1]["pick"] = "3"
    third_picks[-2]["pick"] = "3"
    third = sfc14.check_ticket({"picks": third_picks}, None, draw)
    assert third["hit"] is False
    assert third["prize_level"] is None
    assert "未中奖" in third["message"]


def test_sfc14_check_incomplete_result_degrades():
    results = list(SFC_RESULTS)
    results[0] = None
    result = sfc14.check_ticket({"picks": _picks(SFC_RESULTS)}, None, _sfc_draw(results))
    assert result == {
        "ok": False,
        "hit": False,
        "prize_level": None,
        "detail": {"issue": "26168", "reason": "incomplete"},
        "message": "赛果不完整，暂时无法核对，请稍后重试",
    }


# ---------------------------------------------------------------------------
# 任选9场
# ---------------------------------------------------------------------------


def test_rx9_shares_sfc_data(monkeypatch):
    monkeypatch.setattr(
        sfc14,
        "_fetch_text",
        _fetcher({sfc14.LATEST_URL: _sfc_page()}, {"26168": _sfc_xml()}),
    )
    draws = rx9.fetch_draws(limit=1)
    assert rx9.SOURCE_NAME == sfc14.SOURCE_NAME
    assert draws[0]["issue"] == "26168"
    assert len(draws[0]["matches"]) == 14


def test_rx9_validate_boundaries():
    picks = [{"index": index, "pick": "3"} for index in range(1, 10)]
    assert rx9.validate_ticket({"picks": picks})["ok"] is True

    assert rx9.validate_ticket({"picks": picks[:8]})["ok"] is False

    duplicated = [dict(item) for item in picks]
    duplicated[-1]["index"] = 8
    assert rx9.validate_ticket({"picks": duplicated})["ok"] is False

    out_of_range = [dict(item) for item in picks]
    out_of_range[-1]["index"] = 15
    result = rx9.validate_ticket({"picks": out_of_range})
    assert result["ok"] is False
    assert any("1–14" in error for error in result["errors"])

    invalid = [dict(item) for item in picks]
    invalid[0]["pick"] = "2"
    assert rx9.validate_ticket({"picks": invalid})["ok"] is False


def test_rx9_check_hit_miss_and_incomplete():
    draw = _sfc_draw()
    picks = [{"index": index, "pick": SFC_RESULTS[index - 1]} for index in range(1, 10)]

    hit = rx9.check_ticket({"picks": picks}, None, draw)
    assert hit["hit"] is True
    assert hit["prize_level"] == "任选9场"
    assert hit["detail"]["hits"] == 9
    assert "官方公告" in hit["message"]

    miss_picks = [dict(item) for item in picks]
    miss_picks[0]["pick"] = "0" if miss_picks[0]["pick"] != "0" else "3"
    miss = rx9.check_ticket({"picks": miss_picks}, None, draw)
    assert miss["hit"] is False
    assert miss["prize_level"] is None
    assert miss["detail"]["hits"] == 8
    assert miss["detail"]["wrong_indexes"] == [1]

    incomplete_results = list(SFC_RESULTS)
    incomplete_results[4] = None
    degraded = rx9.check_ticket(
        {"picks": picks}, None, _sfc_draw(incomplete_results)
    )
    assert degraded["ok"] is False
    assert degraded["hit"] is False
    assert degraded["message"] == "赛果不完整，暂时无法核对，请稍后重试"


# ---------------------------------------------------------------------------
# 4场进球
# ---------------------------------------------------------------------------


def test_jq4_page_fallback_does_not_guess_ambiguous_total(monkeypatch):
    monkeypatch.setattr(
        sfc14,
        "_fetch_text",
        _fetcher({jq4.LATEST_URL: _jq4_page()}),
    )
    draw = jq4.fetch_draws(limit=1)[0]

    assert draw["issue"] == "26243"
    assert len(draw["matches"]) == 4
    # 1+1=2 可确定；3+ 对 0 无法确定是 3 还是 3+，置为 None
    assert draw["matches"][2]["result"] == "2"
    assert draw["matches"][0]["result"] is None
    assert draw["matches"][3]["result"] == "3+"
    assert draw["extra"]["incomplete"] is True
    assert draw["extra"]["incomplete_indexes"] == [1, 2]


def test_jq4_fetch_with_xml_scores(monkeypatch):
    monkeypatch.setattr(
        sfc14,
        "_fetch_text",
        _fetcher({jq4.LATEST_URL: _jq4_page()}, {"26243": _jq4_xml()}),
    )
    draw = jq4.fetch_draws(limit=1)[0]

    assert [match["result"] for match in draw["matches"]] == JQ4_BUCKETS
    assert [match["score"] for match in draw["matches"]] == JQ4_SCORES
    assert draw["extra"]["incomplete"] is False


def test_jq4_validate_boundaries():
    picks = [
        {"index": 1, "pick": "3"},
        {"index": 2, "pick": "3+"},
        {"index": 3, "pick": "2"},
        {"index": 4, "pick": "3"},
    ]
    validated = jq4.validate_ticket({"picks": picks})
    assert validated["ok"] is True
    assert [item["pick"] for item in validated["normalized"]["picks"]] == JQ4_BUCKETS

    assert jq4.validate_ticket("3/1/2/0")["ok"] is True

    duplicated = [dict(item) for item in picks]
    duplicated[-1]["index"] = 3
    assert jq4.validate_ticket({"picks": duplicated})["ok"] is False

    invalid = [dict(item) for item in picks]
    invalid[0]["pick"] = "4"
    assert jq4.validate_ticket({"picks": invalid})["ok"] is False

    assert jq4.validate_ticket({"picks": picks[:3]})["ok"] is False


def test_jq4_check_hit_miss_and_incomplete():
    draw = _sfc_draw()
    draw["matches"] = [
        {
            "index": index + 1,
            "home": f"主队{index + 1}",
            "away": f"客队{index + 1}",
            "score": JQ4_SCORES[index],
            "half_score": None,
            "result": value,
            "half_result": None,
        }
        for index, value in enumerate(JQ4_BUCKETS)
    ]
    picks = [{"index": index + 1, "pick": value} for index, value in enumerate(JQ4_BUCKETS)]

    hit = jq4.check_ticket({"picks": picks}, None, draw)
    assert hit["hit"] is True and hit["prize_level"] == "一等奖"
    assert hit["detail"]["hits"] == 4
    assert "官方公告" in hit["message"]

    miss_picks = [dict(item) for item in picks]
    miss_picks[3]["pick"] = "0"
    miss = jq4.check_ticket({"picks": miss_picks}, None, draw)
    assert miss["hit"] is False
    assert miss["prize_level"] is None
    assert miss["detail"]["wrong_indexes"] == [4]

    draw["matches"][1]["result"] = None
    degraded = jq4.check_ticket({"picks": picks}, None, draw)
    assert degraded["ok"] is False
    assert degraded["message"] == "赛果不完整，暂时无法核对，请稍后重试"


# ---------------------------------------------------------------------------
# 6场半全场
# ---------------------------------------------------------------------------


def test_bqc6_fetch_page_and_xml_scores(monkeypatch):
    monkeypatch.setattr(
        sfc14,
        "_fetch_text",
        _fetcher({bqc6.LATEST_URL: _zc6_page()}, {"26236": _zc6_xml()}),
    )
    draw = bqc6.fetch_draws(limit=1)[0]

    assert draw["issue"] == "26236"
    assert len(draw["matches"]) == 6
    assert [(m["half_result"], m["result"]) for m in draw["matches"]] == ZC6_PAIRS
    assert draw["matches"][0]["score"] == "4:0"
    assert draw["matches"][0]["half_score"] == "2:0"
    assert draw["extra"]["incomplete"] is False


def test_bqc6_page_only_still_has_half_and_full(monkeypatch):
    monkeypatch.setattr(
        sfc14,
        "_fetch_text",
        _fetcher({bqc6.LATEST_URL: _zc6_page()}),
    )
    draw = bqc6.fetch_draws(limit=1)[0]
    assert [(m["half_result"], m["result"]) for m in draw["matches"]] == ZC6_PAIRS
    assert draw["extra"]["incomplete"] is False


def test_bqc6_validate_boundaries():
    picks = [
        {"index": index + 1, "half": half, "full": full}
        for index, (half, full) in enumerate(ZC6_PAIRS)
    ]
    assert bqc6.validate_ticket({"picks": picks})["ok"] is True
    assert bqc6.validate_ticket("33/33/11/10/33/33")["ok"] is True

    duplicated = [dict(item) for item in picks]
    duplicated[-1]["index"] = 5
    assert bqc6.validate_ticket({"picks": duplicated})["ok"] is False

    invalid_half = [dict(item) for item in picks]
    invalid_half[0]["half"] = "2"
    result = bqc6.validate_ticket({"picks": invalid_half})
    assert result["ok"] is False
    assert any("半场" in error for error in result["errors"])

    invalid_full = [dict(item) for item in picks]
    invalid_full[1]["full"] = None
    assert bqc6.validate_ticket({"picks": invalid_full})["ok"] is False

    assert bqc6.validate_ticket({"picks": picks[:5]})["ok"] is False


def test_bqc6_check_hit_miss_and_incomplete():
    matches = [
        {
            "index": index + 1,
            "home": f"主队{index + 1}",
            "away": f"客队{index + 1}",
            "score": ZC6_SCORES[index][1],
            "half_score": ZC6_SCORES[index][0],
            "result": full,
            "half_result": half,
        }
        for index, (half, full) in enumerate(ZC6_PAIRS)
    ]
    draw = {"issue": "26236", "date": "2026-11-24", "matches": matches, "extra": {}}
    picks = [
        {"index": index + 1, "half": half, "full": full}
        for index, (half, full) in enumerate(ZC6_PAIRS)
    ]

    hit = bqc6.check_ticket({"picks": picks}, None, draw)
    assert hit["hit"] is True and hit["prize_level"] == "一等奖"
    assert hit["detail"]["hits"] == 12
    assert len(hit["detail"]["matches"]) == 6
    assert all(item["half_hit"] and item["full_hit"] for item in hit["detail"]["matches"])
    assert "官方公告" in hit["message"]

    miss_picks = [dict(item) for item in picks]
    miss_picks[3]["full"] = "3"
    miss = bqc6.check_ticket({"picks": miss_picks}, None, draw)
    assert miss["hit"] is False
    assert miss["detail"]["hits"] == 11
    target = next(item for item in miss["detail"]["matches"] if item["index"] == 4)
    assert target["half_hit"] is True
    assert target["full_hit"] is False

    draw["matches"][1]["half_result"] = None
    degraded = bqc6.check_ticket({"picks": picks}, None, draw)
    assert degraded["ok"] is False
    assert degraded["message"] == "赛果不完整，暂时无法核对，请稍后重试"


def test_bqc6_fetch_xml_first_when_page_blocked(monkeypatch):
    pages = {
        bqc6.LATEST_URL: "<html><body>503 服务暂不可用</body></html>",
        sfc14.LATEST_URL: _sfc_page(),
    }
    monkeypatch.setattr(
        sfc14,
        "_fetch_text",
        _fetcher(pages, {"26168": _zc6_xml(issue="26168")}),
    )

    draws = bqc6.fetch_draws(limit=2)

    assert draws[0]["issue"] == "26168"
    assert len(draws[0]["matches"]) == 6
    assert [(m["half_result"], m["result"]) for m in draws[0]["matches"]] == ZC6_PAIRS
    assert draws[0]["extra"]["incomplete"] is False


def test_bqc6_fetch_all_sources_fail_raises(monkeypatch):
    def broken_fetch(url, encoding="gb18030"):
        raise RuntimeError("站点不可用")

    monkeypatch.setattr(sfc14, "_fetch_text", broken_fetch)
    with pytest.raises(ValueError):
        bqc6.fetch_draws(limit=1)


def test_sfc14_history_capped_to_three(monkeypatch):
    history = ("26167", "26166", "26165", "26164", "26163")
    pages = {
        sfc14.LATEST_URL: _sfc_page(history=history),
    }
    for issue in history:
        pages[sfc14.HISTORY_URL.format(issue=issue)] = _sfc_page(
            issue=issue, date="2026年11月22日"
        )
    monkeypatch.setattr(sfc14, "_fetch_text", _fetcher(pages, {}))

    draws = sfc14.fetch_draws(limit=30)

    assert [draw["issue"] for draw in draws] == ["26168", "26167", "26166", "26165"]


# ---------------------------------------------------------------------------
# API 端到端与缓存降级
# ---------------------------------------------------------------------------


def test_api_bqc6_draws_when_page_blocked(client, monkeypatch):
    pages = {
        bqc6.LATEST_URL: "<html><body>503 服务暂不可用</body></html>",
        sfc14.LATEST_URL: _sfc_page(),
    }
    monkeypatch.setattr(
        sfc14,
        "_fetch_text",
        _fetcher(pages, {"26168": _zc6_xml(issue="26168")}),
    )

    resp = client.get("/api/helper/games/bqc6/draws", params={"refresh": "true"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["draws"][0]["issue"] == "26168"
    assert len(body["draws"][0]["matches"]) == 6


def test_api_bqc6_refresh_failure_keeps_old_cache(client, monkeypatch):
    games_api.reset_refresh_state()
    old_matches = [
        {
            "index": index + 1,
            "home": f"主队{index + 1}",
            "away": f"客队{index + 1}",
            "score": ZC6_SCORES[index][1],
            "half_score": ZC6_SCORES[index][0],
            "result": full,
            "half_result": half,
        }
        for index, (half, full) in enumerate(ZC6_PAIRS)
    ]
    old_draw = {
        "issue": "26230",
        "date": "2026-11-18",
        "numbers": {},
        "matches": old_matches,
        "extra": {},
    }
    assert cache.save_cache("bqc6", [old_draw], "旧缓存") is not None
    before = cache.load_cache("bqc6")

    def broken_fetch(url, encoding="gb18030"):
        raise RuntimeError("站点不可用")

    monkeypatch.setattr(sfc14, "_fetch_text", broken_fetch)

    resp = client.post("/api/helper/games/bqc6/refresh")
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is False
    assert body["status"] == "stale"
    assert body["latest_issue"] == "26230"

    after = cache.load_cache("bqc6")
    assert after["source"] == "旧缓存"
    assert after["updated_at"] == before["updated_at"]
    assert [draw["issue"] for draw in after["draws"]] == ["26230"]


def test_api_sfc14_draws_and_check(client, monkeypatch):
    monkeypatch.setattr(
        sfc14,
        "_fetch_text",
        _fetcher({sfc14.LATEST_URL: _sfc_page()}, {"26168": _sfc_xml()}),
    )

    resp = client.get("/api/helper/games/sfc14/draws")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["source"] == sfc14.SOURCE_NAME
    assert body["notice"] is None
    assert body["draws"][0]["issue"] == "26168"
    assert len(body["draws"][0]["matches"]) == 14

    checked = client.post(
        "/api/helper/check",
        json={
            "game_code": "sfc14",
            "play_type": None,
            "payload": {"picks": _picks(SFC_RESULTS)},
        },
    )
    assert checked.status_code == 200
    checked_body = checked.json()
    assert checked_body["game_code"] == "sfc14"
    assert checked_body["draw"] == {"issue": "26168", "date": "2026-11-23"}
    assert checked_body["result"]["hit"] is True
    assert checked_body["result"]["prize_level"] == "一等奖"


def test_api_sfc14_refresh_failure_keeps_old_cache(client, monkeypatch):
    games_api.reset_refresh_state()
    old_draw = _sfc_draw(issue="26160", date="2026-11-01")
    assert cache.save_cache("sfc14", [old_draw], "旧缓存") is not None
    before = cache.load_cache("sfc14")

    def broken_fetch(url, encoding="gb18030"):
        raise RuntimeError("模拟数据源不可用")

    monkeypatch.setattr(sfc14, "_fetch_text", broken_fetch)

    resp = client.post("/api/helper/games/sfc14/refresh")
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is False
    assert body["status"] == "stale"
    assert body["latest_issue"] == "26160"
    assert body["message"] == "数据源暂不可用，已保留上次缓存"

    after = cache.load_cache("sfc14")
    assert after["source"] == "旧缓存"
    assert after["updated_at"] == before["updated_at"]
    assert [draw["issue"] for draw in after["draws"]] == ["26160"]

    # 手动刷新有 30 秒节流；清理状态以验证 draws?refresh=true 的降级路径
    games_api.reset_refresh_state()
    fallback = client.get(
        "/api/helper/games/sfc14/draws", params={"refresh": "true"}
    )
    assert fallback.status_code == 200
    fallback_body = fallback.json()
    assert fallback_body["status"] == "stale"
    assert fallback_body["notice"] == "数据源暂不可用，已显示上次缓存"
    assert fallback_body["draws"][0]["issue"] == "26160"
