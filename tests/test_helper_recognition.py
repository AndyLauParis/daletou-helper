"""票据识别积累测试：权限、异步落库、校验、去重、并发、导出与同步。"""

from __future__ import annotations

import csv
import io
import json
import threading

import pytest
from fastapi.testclient import TestClient

from helper import config
from helper import db as db_module
from helper import recognition
from helper.api import auth as auth_api
from helper.api import recognition as recognition_api
from helper.security import hash_password, utc_now_iso
from helper_app import app

PASSWORD = "Str0ngPassw0rd"
PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"0" * 64

DLT_RESULT = {
    "game_code": "dlt",
    "issue": "26135",
    "play_type": "standard",
    "payload": {"front": ["01", "07", "12", "23", "35"], "back": ["03", "11"]},
    "confidence": 0.95,
    "field_confidence": {"game_code": 0.99, "issue": 0.96, "payload": 0.92},
    "ticket_no": "T123456",
    "raw_text": "超级大乐透 第26135期",
    "model": "fake-vision",
    "provider": "test",
}


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", str(tmp_path / "helper.db"))
    auth_api.reset_login_rate_limit()
    with TestClient(app) as test_client:
        yield test_client
    auth_api.reset_login_rate_limit()


def register(client, username="alice") -> str:
    resp = client.post(
        "/api/helper/auth/register",
        json={"username": username, "password": PASSWORD, "is_adult": True},
    )
    assert resp.status_code == 201
    return resp.json()["token"]


def auth_header(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def fake_ocr(monkeypatch, result=None, error=None):
    def _fake(image_bytes, mime, game_hint=None):
        if error is not None:
            raise error
        return dict(result or DLT_RESULT)

    monkeypatch.setattr(recognition_api.ocr, "recognize_ticket", _fake)


def scan(client, token, **data):
    return client.post(
        "/api/helper/recognition/scan",
        headers=auth_header(token),
        files={"image": ("ticket.png", PNG_BYTES, "image/png")},
        data=data or {"game_code": "", "issue": ""},
    )


def manual(client, token, **overrides):
    body = {
        "game_code": "ssq",
        "issue": "26130",
        "play_type": None,
        "payload": {"red": ["01", "02", "03", "04", "05", "06"], "blue": ["07"]},
        "confidence": 0.95,
        "field_confidence": {"payload": 0.95},
        "source": "manual",
    }
    body.update(overrides)
    return client.post(
        "/api/helper/recognition/records",
        headers=auth_header(token),
        json=body,
    )


def test_requires_login(client):
    assert client.get("/api/helper/recognition/records").status_code == 401
    assert client.get("/api/helper/recognition/stats").status_code == 401
    assert client.get("/api/helper/recognition/config").status_code == 401
    assert scan(client, "bad-token").status_code == 401


def test_scan_persists_record_via_background_task(client, monkeypatch):
    token = register(client)
    fake_ocr(monkeypatch)

    resp = scan(client, token)
    assert resp.status_code == 202
    queued = resp.json()
    assert queued["queued"] is True
    assert queued["record"]["status"] == "valid"
    assert queued["record"]["numbers_text"].startswith("前区 01 07 12 23 35")

    listing = client.get(
        "/api/helper/recognition/records", headers=auth_header(token)
    ).json()
    assert listing["total"] == 1
    item = listing["items"][0]
    assert item["game_code"] == "dlt"
    assert item["issue"] == "26135"
    assert item["source"] == "ocr"
    assert item["seen_count"] == 1
    assert item["confidence"] == pytest.approx(0.95)


def test_scan_without_ocr_config_returns_503(client, monkeypatch):
    token = register(client)
    fake_ocr(
        monkeypatch,
        error=recognition_api.ocr.OcrNotConfigured("识别服务尚未配置"),
    )
    assert scan(client, token).status_code == 503


def test_scan_rejects_invalid_image(client):
    token = register(client)
    resp = client.post(
        "/api/helper/recognition/scan",
        headers=auth_header(token),
        files={"image": ("ticket.txt", b"not an image", "text/plain")},
    )
    assert resp.status_code == 400


def test_low_confidence_marks_review(client, monkeypatch):
    token = register(client)
    low = dict(DLT_RESULT)
    low["confidence"] = 0.4
    low["field_confidence"] = {"issue": 0.4, "payload": 0.4}
    fake_ocr(monkeypatch, low)

    resp = scan(client, token)
    assert resp.status_code == 202
    assert resp.json()["record"]["status"] == "review"

    item = client.get(
        "/api/helper/recognition/records", headers=auth_header(token)
    ).json()["items"][0]
    assert item["status"] == "review"
    assert "置信度" in item["anomaly_reason"]


def test_invalid_numbers_are_marked_anomaly(client, monkeypatch):
    token = register(client)
    bad = dict(DLT_RESULT)
    bad["payload"] = {"front": ["01", "02", "03"], "back": ["04"]}
    fake_ocr(monkeypatch, bad)

    resp = scan(client, token)
    assert resp.status_code == 202
    assert resp.json()["record"]["status"] == "anomaly"
    item = client.get(
        "/api/helper/recognition/records", headers=auth_header(token)
    ).json()["items"][0]
    assert item["status"] == "anomaly"
    assert "前区" in item["anomaly_reason"]


def test_duplicate_scan_merges_and_counts(client, monkeypatch):
    token = register(client)
    fake_ocr(monkeypatch)

    first = scan(client, token)
    second = scan(client, token)
    assert first.status_code == 202 and second.status_code == 202

    listing = client.get(
        "/api/helper/recognition/records", headers=auth_header(token)
    ).json()
    assert listing["total"] == 1
    item = listing["items"][0]
    assert item["seen_count"] == 2
    assert item["revision"] == 2
    assert item["numbers_text"] == first.json()["record"]["numbers_text"]


def test_records_are_isolated_per_user(client, monkeypatch):
    alice = register(client, "alice")
    fake_ocr(monkeypatch)
    scan(client, alice)
    alice_id = client.get(
        "/api/helper/recognition/records", headers=auth_header(alice)
    ).json()["items"][0]["id"]

    bob = register(client, "bob")
    assert client.get(
        "/api/helper/recognition/records", headers=auth_header(bob)
    ).json()["total"] == 0
    assert client.get(
        f"/api/helper/recognition/records/{alice_id}", headers=auth_header(bob)
    ).status_code == 404
    assert client.patch(
        f"/api/helper/recognition/records/{alice_id}",
        headers=auth_header(bob),
        json={"status": "valid"},
    ).status_code == 404


def test_filters_and_stats(client):
    token = register(client)
    manual(client, token, issue="26130", recognized_at="2026-11-01T00:00:00+00:00")
    manual(
        client,
        token,
        game_code="dlt",
        issue="26135",
        play_type="standard",
        payload={"front": ["01", "02", "03", "04", "05"], "back": ["06", "07"]},
        recognized_at="2026-11-20T00:00:00+00:00",
    )

    by_game = client.get(
        "/api/helper/recognition/records?game_code=dlt", headers=auth_header(token)
    ).json()
    assert by_game["total"] == 1
    assert by_game["items"][0]["issue"] == "26135"

    by_issue = client.get(
        "/api/helper/recognition/records?issue=26130", headers=auth_header(token)
    ).json()
    assert by_issue["total"] == 1

    by_date = client.get(
        "/api/helper/recognition/records?date_from=2026-11-10",
        headers=auth_header(token),
    ).json()
    assert by_date["total"] == 1

    stats = client.get(
        "/api/helper/recognition/stats", headers=auth_header(token)
    ).json()
    assert stats["total"] == 2
    assert stats["by_status"]["valid"] == 2
    assert len(stats["by_game"]) == 2

    invalid = client.get(
        "/api/helper/recognition/records?status=oops", headers=auth_header(token)
    )
    assert invalid.status_code == 400


def test_export_csv_and_json(client):
    token = register(client)
    manual(client, token)

    csv_resp = client.get(
        "/api/helper/recognition/export?format=csv", headers=auth_header(token)
    )
    assert csv_resp.status_code == 200
    assert csv_resp.headers["content-type"].startswith("text/csv")
    assert "attachment" in csv_resp.headers["content-disposition"]
    rows = list(csv.reader(io.StringIO(csv_resp.text.lstrip("\ufeff"))))
    assert rows[0][0] == "ID"
    assert "双色球" in rows[1]

    json_resp = client.get(
        "/api/helper/recognition/export?format=json", headers=auth_header(token)
    )
    payload = json_resp.json()
    assert payload["count"] == 1
    assert payload["items"][0]["game_code"] == "ssq"
    assert payload["items"][0]["payload"]["red"]

    assert client.get(
        "/api/helper/recognition/export?format=xml", headers=auth_header(token)
    ).status_code == 400


def test_patch_status_and_revalidate(client):
    token = register(client)
    monkeypatch_confidence = 0.4
    manual(client, token, confidence=monkeypatch_confidence)

    item = client.get(
        "/api/helper/recognition/records", headers=auth_header(token)
    ).json()["items"][0]
    assert item["status"] == "review"

    updated = client.patch(
        f"/api/helper/recognition/records/{item['id']}",
        headers=auth_header(token),
        json={"status": "valid", "review_note": "人工核对无误"},
    )
    assert updated.status_code == 200
    assert updated.json()["status"] == "valid"
    assert updated.json()["reviewed"] is True
    assert updated.json()["review_note"] == "人工核对无误"

    assert client.patch(
        f"/api/helper/recognition/records/{item['id']}",
        headers=auth_header(token),
        json={"status": "bogus"},
    ).status_code == 400

    result = client.post(
        "/api/helper/recognition/revalidate", headers=auth_header(token)
    )
    assert result.status_code == 200
    assert result.json()["checked"] == 0


def test_sync_incremental_full_and_merge(client):
    token = register(client)
    manual(client, token)

    full = client.get(
        "/api/helper/recognition/sync?full=1", headers=auth_header(token)
    ).json()
    assert full["full"] is True
    assert len(full["items"]) == 1
    assert full["next_cursor"] == full["items"][0]["id"]

    incremental = client.get(
        "/api/helper/recognition/sync?since=1970-01-01T00:00:00+00:00",
        headers=auth_header(token),
    ).json()
    assert incremental["full"] is False
    assert len(incremental["items"]) == 1

    sync_body = {
        "records": [
            {
                "game_code": "ssq",
                "issue": "26131",
                "payload": {
                    "red": ["02", "03", "04", "05", "06", "07"],
                    "blue": ["08"],
                },
                "confidence": 0.9,
                "field_confidence": {"payload": 0.9},
                "recognized_at": "2030-01-01T00:00:00+00:00",
                "updated_at": "2030-01-01T00:00:00+00:00",
            }
        ]
    }
    inserted = client.post(
        "/api/helper/recognition/sync", headers=auth_header(token), json=sync_body
    ).json()
    assert inserted["inserted"] == 1

    stale = json.loads(json.dumps(sync_body))
    stale["records"][0]["updated_at"] = "2020-01-01T00:00:00+00:00"
    skipped = client.post(
        "/api/helper/recognition/sync", headers=auth_header(token), json=stale
    ).json()
    assert skipped["skipped"] == 1

    newer = json.loads(json.dumps(sync_body))
    newer["records"][0]["updated_at"] = "2031-01-01T00:00:00+00:00"
    newer["records"][0]["confidence"] = 0.97
    updated = client.post(
        "/api/helper/recognition/sync", headers=auth_header(token), json=newer
    ).json()
    assert updated["updated"] == 1
    assert client.get(
        "/api/helper/recognition/records", headers=auth_header(token)
    ).json()["total"] == 2

    too_many = {"records": [{}] * (recognition.MAX_SYNC_BATCH + 1)}
    assert client.post(
        "/api/helper/recognition/sync", headers=auth_header(token), json=too_many
    ).status_code == 400


def test_concurrent_upsert_deduplicates(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", str(tmp_path / "concurrent.db"))
    db_module.init_db()
    conn = db_module.connect()
    try:
        password_hash, salt = hash_password(PASSWORD)
        cursor = conn.execute(
            "INSERT INTO users (username, password_hash, password_salt, is_adult, created_at) "
            "VALUES (?, ?, ?, 1, ?)",
            ("racer", password_hash, salt, utc_now_iso()),
        )
        user_id = int(cursor.lastrowid)
        conn.commit()
    finally:
        conn.close()

    prepared = recognition.validate_record(
        "dlt",
        "26135",
        {"front": ["01", "02", "03", "04", "05"], "back": ["06", "07"]},
        "standard",
        0.95,
        {"payload": 0.95},
    )
    errors: list[Exception] = []

    def worker() -> None:
        connection = db_module.connect()
        try:
            recognition.upsert_record(connection, user_id, prepared, source="ocr")
            connection.commit()
        except Exception as exc:  # pragma: no cover - 失败时由断言暴露
            errors.append(exc)
        finally:
            connection.close()

    threads = [threading.Thread(target=worker) for _ in range(10)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert not errors
    conn = db_module.connect()
    try:
        rows = conn.execute(
            "SELECT seen_count FROM recognition_records WHERE user_id = ?",
            (user_id,),
        ).fetchall()
    finally:
        conn.close()
    assert len(rows) == 1
    assert rows[0]["seen_count"] == 10


def test_recognition_page_available(client):
    resp = client.get("/recognition")
    assert resp.status_code == 200
    assert "票据识别" in resp.text
    assert "/static/js/recognition.js" in resp.text
