"""OCR 文本解析与 ModelBest 适配测试。"""

from __future__ import annotations

import pytest

from helper import config
from helper import ocr, ticket_parse

PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"0" * 64

DLT_TEXT = (
    "中国体育彩票 超级大乐透\n"
    "第26135期\n"
    "前区：01 07 12 23 35\n"
    "后区：03 11\n"
    "2026-11-26 10:30\n"
    "票号 T123456789"
)


def test_parse_dlt_labeled():
    result = ticket_parse.parse_ticket_text(DLT_TEXT)
    assert result["game_code"] == "dlt"
    assert result["issue"] == "26135"
    assert result["payload"] == {"front": [1, 7, 12, 23, 35], "back": [3, 11]}
    assert result["play_type"] == "standard"
    assert result["ticket_no"] == "T123456789"
    assert result["confidence"] >= 0.8


def test_parse_dlt_unlabeled_block_text_with_hint():
    text = "26135\n\n0107122335\n\n03 11\n\n2026-11-26 10:30\n\nT123456789"
    result = ticket_parse.parse_ticket_text(text, "dlt")
    assert result["issue"] == "26135"
    assert result["payload"] == {"front": [1, 7, 12, 23, 35], "back": [3, 11]}
    # 无号码标签时置信度应低于阈值，交给人工审核
    assert result["confidence"] < 0.8


def test_parse_ssq_labeled():
    text = "双色球 第26130期 红球：01 02 03 04 05 06 蓝球：07"
    result = ticket_parse.parse_ticket_text(text)
    assert result["game_code"] == "ssq"
    assert result["payload"] == {"red": [1, 2, 3, 4, 5, 6], "blue": [7]}
    assert result["confidence"] >= 0.8


def test_parse_pl3_ignores_game_name_digit():
    text = "中国体育彩票 排列3 第26135期 开奖号码 1 2 3"
    result = ticket_parse.parse_ticket_text(text)
    assert result["game_code"] == "pl3"
    assert result["payload"] == {"digits": [1, 2, 3]}
    assert result["play_type"] == "zhixuan"


def test_parse_fc3d_and_qlc():
    fc3d = ticket_parse.parse_ticket_text("福彩3D 第26135期 号码 6 4 8")
    assert fc3d["game_code"] == "fc3d"
    assert fc3d["payload"]["digits"] == [6, 4, 8]

    qlc = ticket_parse.parse_ticket_text(
        "七乐彩 第26140期 基本号码：01 03 05 07 09 11 13"
    )
    assert qlc["game_code"] == "qlc"
    assert qlc["payload"]["basic"] == [1, 3, 5, 7, 9, 11, 13]


def test_parse_unknown_game_raises():
    with pytest.raises(ticket_parse.TicketParseError):
        ticket_parse.parse_ticket_text("某某票据 123456")


def test_modelbest_mode_uses_blocks(monkeypatch):
    monkeypatch.setattr(config, "OCR_MODE", "modelbest")
    monkeypatch.setattr(config, "OCR_BASE_URL", "https://example.com/v1")
    monkeypatch.setattr(config, "OCR_API_KEY", "test-key")
    monkeypatch.setattr(config, "OCR_MODEL", "MiniCPM-OCR-1.0")

    calls = {}

    def fake_post(url, payload):
        calls["url"] = url
        calls["payload"] = payload
        return {
            "choices": [{"message": {"content": "ignored"}}],
            "ocr": {
                "blocks": [
                    {"order": 3, "content": "后区：03 11"},
                    {"order": 2, "content": "前区：01 07 12 23 35"},
                    {"order": 1, "content": "第26135期"},
                    {"order": 0, "content": "超级大乐透"},
                ]
            },
        }

    monkeypatch.setattr(ocr, "_post_json", fake_post)
    result = ocr.recognize_ticket(PNG_BYTES, "image/png", "dlt")

    assert calls["url"] == "https://example.com/v1/document-parse"
    assert calls["payload"]["model"] == "MiniCPM-OCR-1.0"
    assert calls["payload"]["image"].startswith("data:image/png;base64,")
    assert calls["payload"]["upright"] is True
    assert result["game_code"] == "dlt"
    assert result["issue"] == "26135"
    assert result["payload"] == {"front": [1, 7, 12, 23, 35], "back": [3, 11]}
