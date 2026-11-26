"""全国彩票购彩辅助工具 —— 独立 FastAPI 应用（默认端口 8100）。

与现有“大乐透数学实验室”（app.py，端口 8000）完全独立：
不修改 app.py、core/、static/，仅只读复用 core.store 的开奖数据。
"""

from __future__ import annotations

import importlib
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from helper import config
from helper.db import init_db
from security_layer import install_security

logger = logging.getLogger("helper")
logging.basicConfig(level=logging.INFO)

ROUTER_MODULES = [
    "helper.api.auth",
    "helper.api.games",
    "helper.api.records",
    "helper.api.budget",
    "helper.api.reminders",
    "helper.api.data",
    "helper.api.lab",
    "helper.api.picker",
    "helper.api.feedback",
    "helper.api.recognition",
    "helper.api.admin",
]

# 生产环境默认关闭 /docs 与 /openapi.json；需要调试时设置 HELPER_ENABLE_DOCS=1
_DOCS_ENABLED = os.environ.get("HELPER_ENABLE_DOCS", "").strip().lower() in {
    "1",
    "true",
    "yes",
}


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        init_db()
        logger.info("购彩辅助工具数据库就绪：%s", config.DB_PATH)
    except Exception:
        logger.exception("购彩辅助工具数据库初始化失败")
    try:
        from core.store import ensure_data

        status = ensure_data()
        logger.info(
            "开奖数据可用：%s 期，最新 %s",
            status.get("count"),
            status.get("latest_issue"),
        )
    except Exception:
        logger.warning("现有开奖数据初始化失败，不影响账号与记录功能", exc_info=True)

    watcher = None
    try:
        from helper.draw_watcher import start_draw_watcher

        watcher = start_draw_watcher()
    except Exception:
        logger.warning("开奖自动更新启动失败，不影响手动刷新", exc_info=True)

    try:
        yield
    finally:
        if watcher is not None:
            try:
                from helper.draw_watcher import stop_draw_watcher

                stop_draw_watcher()
            except Exception:
                logger.warning("开奖自动更新停止失败", exc_info=True)


app = FastAPI(
    title=config.APP_TITLE,
    lifespan=lifespan,
    docs_url="/docs" if _DOCS_ENABLED else None,
    redoc_url="/redoc" if _DOCS_ENABLED else None,
    openapi_url="/openapi.json" if _DOCS_ENABLED else None,
)

_cors_origins = [
    origin.strip()
    for origin in os.environ.get("HELPER_CORS_ORIGINS", "").split(",")
    if origin.strip()
]
if _cors_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_cors_origins,
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

install_security(app, app_name="helper")

app.mount(
    "/static",
    StaticFiles(directory=str(config.STATIC_DIR), check_dir=False),
    name="static",
)


def _register_routers(application: FastAPI) -> None:
    for module_name in ROUTER_MODULES:
        try:
            module = importlib.import_module(module_name)
        except ModuleNotFoundError as exc:
            if exc.name == module_name:
                logger.error(
                    "路由模块 %s 不存在，请修正 ROUTER_MODULES", module_name
                )
            else:
                logger.error(
                    "路由模块 %s 缺少依赖 %s，请先安装依赖", module_name, exc.name
                )
            raise
        module_router = getattr(module, "router", None)
        if module_router is None:
            raise RuntimeError(f"路由模块 {module_name} 缺少 router 对象")
        application.include_router(module_router)


_register_routers(app)


def _page(filename: str) -> FileResponse:
    path = Path(config.STATIC_DIR) / filename
    if not path.exists():
        raise HTTPException(status_code=404, detail="页面暂未开放")
    return FileResponse(path)


@app.get("/")
def index():
    return _page("landing.html")


@app.get("/app")
def app_page():
    return _page("index.html")


@app.get("/lab")
def lab_page():
    return _page("lab.html")


@app.get("/picker")
def picker_page():
    return _page("picker.html")


@app.get("/login")
def login_page():
    return _page("login.html")


@app.get("/register")
def register_page():
    return _page("register.html")


@app.get("/admin")
def admin_page():
    return _page("admin.html")


@app.get("/recognition")
def recognition_page():
    return _page("recognition.html")


@app.get("/api/helper/health")
def health():
    return {"ok": True, "app": "helper"}


if __name__ == "__main__":
    uvicorn.run(
        app,
        host=os.environ.get("HELPER_HOST", "127.0.0.1"),
        port=int(os.environ.get("HELPER_PORT", "8100")),
        proxy_headers=True,
        forwarded_allow_ips=os.environ.get("HELPER_FORWARDED_ALLOW_IPS", "127.0.0.1"),
        server_header=False,
    )
