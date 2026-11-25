"""大乐透三大模型数学验证实验室 —— FastAPI 入口。"""

from __future__ import annotations

import hmac
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlsplit

import uvicorn
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from core import store
from security_layer import client_ip, install_security
from core.constants import (
    ANY_PRIZE_COMBOS,
    ANY_PRIZE_RATE,
    BACK_COMBOS,
    CURRENT_PRIZE_RATE,
    FRONT_COMBOS,
    FRONT_EXPECTED_HITS,
    BACK_EXPECTED_HITS,
    JACKPOT_CAP_ADDON,
    JACKPOT_CAP_BASIC,
    JACKPOT_PROB,
    RETURN_RATE,
    TICKET_PRICE,
    TOTAL_COMBOS,
)

logger = logging.getLogger("dlt")
logging.basicConfig(level=logging.INFO)

PROJECT_ROOT = Path(__file__).resolve().parent
STATIC_DIR = PROJECT_ROOT / "static"
INDEX_FILE = STATIC_DIR / "index.html"

NOT_READY = "module not ready"

# 刷新开奖数据属于管理操作：配置 LAB_ADMIN_TOKEN 后必须携带 X-Admin-Token；
# 未配置时仅允许“直连本机且 Host 为本机地址”的请求（防止反向代理把公网请求
# 以 127.0.0.1 身份转发进来）。
_ADMIN_TOKEN = os.environ.get("LAB_ADMIN_TOKEN", "").strip()
_LOOPBACK_IPS = {"127.0.0.1", "::1", "testclient"}
_LOCAL_HOSTNAMES = {"127.0.0.1", "localhost", "::1", "testserver"}
_FORWARDED_HEADERS = (
    "x-forwarded-for",
    "x-real-ip",
    "x-forwarded-host",
    "x-forwarded-proto",
)

# 生产环境默认关闭 /docs 与 /openapi.json；需要调试时设置 LAB_ENABLE_DOCS=1
_DOCS_ENABLED = os.environ.get("LAB_ENABLE_DOCS", "").strip().lower() in {
    "1",
    "true",
    "yes",
}


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        status = store.ensure_data()
        logger.info("数据就绪：%s 期，最新 %s", status["count"], status["latest_issue"])
    except Exception:
        logger.warning("数据初始化失败，应用继续启动（可能处于离线样例模式）", exc_info=True)
    yield


app = FastAPI(
    title="大乐透三大模型数学验证实验室",
    lifespan=lifespan,
    docs_url="/docs" if _DOCS_ENABLED else None,
    redoc_url="/redoc" if _DOCS_ENABLED else None,
    openapi_url="/openapi.json" if _DOCS_ENABLED else None,
)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR), check_dir=False), name="static")
install_security(app, app_name="lab")


class Model1Request(BaseModel):
    jackpot: float = Field(default=5_000_000, ge=0, le=1_000_000_000)
    second_prize: float = Field(default=100_000, ge=0, le=1_000_000_000)
    pool: float | None = Field(default=None, ge=0, le=1_000_000_000_000)
    price: float = Field(default=2.0, ge=0, le=1000)
    mode: str = Field(default="rules", max_length=16)


class Model2Request(BaseModel):
    jackpot: float = Field(default=5_000_000, ge=0, le=1_000_000_000)
    second_prize: float = Field(default=100_000, ge=0, le=1_000_000_000)
    pool: float | None = Field(default=None, ge=0, le=1_000_000_000_000)
    tickets_per_sec: float = Field(default=1.0, ge=0, le=1_000_000)


class Model3Request(BaseModel):
    base_bet: float = Field(default=2, ge=0, le=1_000_000)
    multiplier: float = Field(default=2, ge=1, le=100)
    bankroll: float = Field(default=10000, ge=0, le=1_000_000_000)
    rounds: int = Field(default=100, ge=1, le=1000)
    simulations: int = Field(default=1000, ge=1, le=5000)
    p_win: float = Field(default=0.0667, ge=0, le=1)
    seed: int = Field(default=42, ge=0, le=2**31 - 1)


class HistoryRequest(BaseModel):
    window: int | None = Field(default=None, ge=1, le=2000)
    periods: int = Field(default=300, ge=1, le=2000)


def _latest_pool() -> int:
    status = store.get_status()
    return status.get("latest_pool") or 0


def _require_module(module_name: str):
    """惰性导入模型模块；未就绪时返回 503。"""
    try:
        return __import__(module_name, fromlist=["*"])
    except ModuleNotFoundError as exc:
        raise HTTPException(status_code=503, detail=NOT_READY) from exc


@app.get("/")
def index():
    if INDEX_FILE.exists():
        return FileResponse(INDEX_FILE)
    return JSONResponse(
        {
            "message": "前端页面尚未就绪，可先访问 API。",
            "endpoints": [
                "/api/health",
                "/api/overview",
                "/api/draws?limit=100",
                "/api/data/refresh",
            ],
        }
    )


@app.get("/api/health")
def health():
    return store.get_status()


def _is_local_request(request: Request) -> bool:
    if client_ip(request) not in _LOOPBACK_IPS:
        return False
    if any(request.headers.get(name) for name in _FORWARDED_HEADERS):
        return False
    host = request.headers.get("host", "").strip().lower()
    try:
        hostname = urlsplit(f"//{host}").hostname or ""
    except ValueError:
        return False
    return hostname in _LOCAL_HOSTNAMES


def _require_admin(request: Request) -> None:
    if _ADMIN_TOKEN:
        provided = request.headers.get("x-admin-token", "")
        if not hmac.compare_digest(
            provided.encode("utf-8"), _ADMIN_TOKEN.encode("utf-8")
        ):
            raise HTTPException(status_code=403, detail="无权刷新数据")
        return
    if not _is_local_request(request):
        raise HTTPException(
            status_code=403,
            detail="刷新接口仅允许本机访问，请在服务端配置 LAB_ADMIN_TOKEN",
        )


@app.post("/api/data/refresh")
def refresh_data(request: Request):
    _require_admin(request)
    try:
        return store.refresh()
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"刷新失败：{exc}") from exc


@app.get("/api/draws")
def draws(limit: int = Query(default=100, ge=1, le=1000)):
    return {"draws": store.get_draws()[:limit]}


@app.get("/api/rules")
def rules(
    pool: float | None = Query(default=None, ge=0, le=1_000_000_000_000),
    mode: str = Query(default="rules", max_length=16),
):
    rules_module = _require_module("core.rules")
    get_rule_table = getattr(rules_module, "get_rule_table", None)
    if get_rule_table is None:
        raise HTTPException(status_code=503, detail=NOT_READY)
    effective_pool = pool if pool is not None else _latest_pool()
    return get_rule_table(pool=effective_pool, mode=mode)


@app.get("/api/overview")
def overview():
    status = store.get_status()
    draws_list = store.get_draws()
    latest = draws_list[0] if draws_list else None
    return {
        "status": status,
        "latest": latest,
        "pool_mode": status["pool_mode"],
        "key_numbers": {
            "front_combos": FRONT_COMBOS,
            "back_combos": BACK_COMBOS,
            "total_combos": TOTAL_COMBOS,
            "jackpot_probability": JACKPOT_PROB,
            "any_prize_combos": ANY_PRIZE_COMBOS,
            "any_prize_rate": ANY_PRIZE_RATE,
            "return_rate": RETURN_RATE,
            "current_prize_rate": CURRENT_PRIZE_RATE,
            "ticket_price": TICKET_PRICE,
            "jackpot_cap_basic": JACKPOT_CAP_BASIC,
            "jackpot_cap_addon": JACKPOT_CAP_ADDON,
            "expected_front_hits": FRONT_EXPECTED_HITS,
            "expected_back_hits": BACK_EXPECTED_HITS,
        },
    }


@app.post("/api/model1")
def model1(req: Model1Request):
    module = _require_module("core.kelly")
    analyze_model1 = getattr(module, "analyze_model1", None)
    if analyze_model1 is None:
        raise HTTPException(status_code=503, detail=NOT_READY)
    pool = req.pool if req.pool is not None else _latest_pool()
    return analyze_model1(
        jackpot=req.jackpot,
        second_prize=req.second_prize,
        pool=pool,
        price=req.price,
        mode=req.mode,
    )


@app.post("/api/model2")
def model2(req: Model2Request):
    module = _require_module("core.coverage")
    analyze_model2 = getattr(module, "analyze_model2", None)
    if analyze_model2 is None:
        raise HTTPException(status_code=503, detail=NOT_READY)
    pool = req.pool if req.pool is not None else _latest_pool()
    return analyze_model2(
        jackpot=req.jackpot,
        second_prize=req.second_prize,
        pool=pool,
        tickets_per_sec=req.tickets_per_sec,
    )


@app.post("/api/model3")
def model3(req: Model3Request):
    module = _require_module("core.martingale")
    analyze_model3 = getattr(module, "analyze_model3", None)
    if analyze_model3 is None:
        raise HTTPException(status_code=503, detail=NOT_READY)
    return analyze_model3(
        base_bet=req.base_bet,
        multiplier=req.multiplier,
        bankroll=req.bankroll,
        rounds=req.rounds,
        simulations=req.simulations,
        p_win=req.p_win,
        seed=req.seed,
    )


@app.post("/api/history/test")
def history_test(req: HistoryRequest):
    module = _require_module("core.history_test")
    analyze_history = getattr(module, "analyze_history", None)
    if analyze_history is None:
        raise HTTPException(status_code=503, detail=NOT_READY)
    return analyze_history(
        draws=store.get_draws(),
        window=req.window,
        periods=req.periods,
    )


if __name__ == "__main__":
    uvicorn.run(
        app,
        host=os.environ.get("LAB_HOST", "127.0.0.1"),
        port=int(os.environ.get("PORT", "8000")),
        proxy_headers=True,
        forwarded_allow_ips=os.environ.get("LAB_FORWARDED_ALLOW_IPS", "127.0.0.1"),
        server_header=False,
    )
