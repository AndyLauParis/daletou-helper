"""大乐透三大模型数学验证实验室 —— FastAPI 入口。"""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from core import store
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


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        status = store.ensure_data()
        logger.info("数据就绪：%s 期，最新 %s", status["count"], status["latest_issue"])
    except Exception:
        logger.warning("数据初始化失败，应用继续启动（可能处于离线样例模式）", exc_info=True)
    yield


app = FastAPI(title="大乐透三大模型数学验证实验室", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR), check_dir=False), name="static")


class Model1Request(BaseModel):
    jackpot: float = 5_000_000
    second_prize: float = 100_000
    pool: float | None = None
    price: float = 2.0
    mode: str = "rules"


class Model2Request(BaseModel):
    jackpot: float = 5_000_000
    second_prize: float = 100_000
    pool: float | None = None
    tickets_per_sec: float = 1.0


class Model3Request(BaseModel):
    base_bet: float = 2
    multiplier: float = 2
    bankroll: float = 10000
    rounds: int = 100
    simulations: int = 1000
    p_win: float = 0.0667
    seed: int = 42


class HistoryRequest(BaseModel):
    window: int | None = None
    periods: int = 300


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


@app.post("/api/data/refresh")
def refresh_data():
    try:
        return store.refresh()
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"刷新失败：{exc}") from exc


@app.get("/api/draws")
def draws(limit: int = 100):
    return {"draws": store.get_draws()[:limit]}


@app.get("/api/rules")
def rules(pool: float | None = None, mode: str = "rules"):
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
    uvicorn.run(app, host="127.0.0.1", port=int(os.environ.get("PORT", "8000")))
