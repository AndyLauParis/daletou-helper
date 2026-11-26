"""页面入口测试：公开落地页、工作台、登录注册页与前端跳转契约。"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from helper import config
from helper.api import auth as auth_api
from helper_app import app

STATIC_DIR = Path(config.STATIC_DIR)
JS_DIR = STATIC_DIR / "js"


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", str(tmp_path / "helper.db"))
    auth_api.reset_login_rate_limit()
    with TestClient(app) as test_client:
        yield test_client
    auth_api.reset_login_rate_limit()


def test_root_returns_public_landing_page(client):
    resp = client.get("/")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/html")
    html = resp.text
    assert "免费注册" in html or "登录" in html
    assert "不代购" in html or "18+" in html


def test_app_page_returns_workbench(client):
    resp = client.get("/app")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/html")
    assert "当前账号" in resp.text


def test_login_page_available(client):
    resp = client.get("/login")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/html")


def test_register_page_available(client):
    resp = client.get("/register")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/html")


def test_landing_script_is_served(client):
    resp = client.get("/static/js/landing.js")
    assert resp.status_code == 200
    assert "javascript" in resp.headers["content-type"].lower()
    assert "draw-preview" in resp.text


def test_static_scripts_require_revalidation(client):
    """脚本必须回源校验，避免发版后浏览器继续使用旧 common.js。"""
    resp = client.get("/static/js/common.js")
    assert resp.status_code == 200
    assert resp.headers.get("cache-control") == "no-cache"


@pytest.mark.parametrize("script_name", ["login.js", "register.js"])
def test_auth_scripts_redirect_to_app(script_name):
    """登录/注册成功后必须跳转工作台 /app，防止回退到落地页 /。"""
    script = (JS_DIR / script_name).read_text(encoding="utf-8")
    targets = re.findall(r'window\.location\.href\s*=\s*"([^"]+)"', script)
    assert targets, f"{script_name} 未找到登录成功后的跳转"
    assert targets == ["/app"]


def test_landing_html_references_script_and_avoids_private_apis():
    html = (STATIC_DIR / "landing.html").read_text(encoding="utf-8")
    assert "/static/js/landing.js" in html
    for private_api in (
        "/api/helper/numbers",
        "/api/helper/budget",
        "/api/helper/reminders",
    ):
        assert private_api not in html


@pytest.mark.parametrize("page", ["feedback.html", "favorites.html"])
def test_new_tool_pages_available(client, page):
    resp = client.get(f"/static/{page}")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/html")
    assert "/static/js/theme.js" in resp.text


def test_all_pages_include_theme_bootstrap_and_dual_color_scheme():
    for path in sorted(STATIC_DIR.glob("*.html")):
        html = path.read_text(encoding="utf-8")
        assert "/static/js/theme.js" in html, f"{path.name} 缺少主题引导脚本"
        assert 'content="light dark"' in html, f"{path.name} 未声明深浅配色"


def test_common_script_exposes_favorites_and_theme_hooks():
    script = (JS_DIR / "common.js").read_text(encoding="utf-8")
    assert "helper_favorites_v1" in script
    assert "helper:favorites-changed" in script
    assert "window.HelperFavorites" in script
    assert "data-theme-toggle" in script
    assert '"/static/favorites.html"' in script
    assert '"/static/feedback.html"' in script
