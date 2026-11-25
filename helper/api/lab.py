"""历史数据实验室 API（公开统计，只读开奖缓存；AI 解读需登录）。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from security_layer import LIMITER

from .. import config, lab, llm
from ..deps import get_current_user
from ..games import registry

router = APIRouter(prefix="/api/helper/lab", tags=["helper-lab"])

_COMMON_NOTE = (
    "全部结果仅描述历史开奖样本，不预测未来开奖、不推荐号码，也不构成投注建议。"
)


@router.get("/games")
def lab_games():
    """可做历史统计的游戏及其缓存样本量。"""
    return {"games": lab.list_games(), "notice": _COMMON_NOTE}


@router.get("/analysis")
def lab_analysis(
    game: str = Query(..., description="游戏代码，例如 dlt"),
    window: int = Query(default=100, ge=lab.MIN_SAMPLE, le=200),
):
    """号码频率、形态分布、随机性检验与策略回测。"""
    code = (game or "").strip().lower()
    if registry.get_game(code) is None:
        raise HTTPException(status_code=404, detail="未找到该彩票游戏")
    if code not in lab.PROFILES:
        raise HTTPException(
            status_code=400,
            detail="该游戏暂不支持历史数据分析，仅支持数字型号码游戏",
        )

    try:
        return lab.analyze(code, window=window)
    except lab.LabDataError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/budget")
def lab_budget(
    game: str = Query(..., description="游戏代码，例如 dlt"),
    periods: int = Query(default=100, ge=1, le=520),
    tickets: int = Query(default=1, ge=1, le=20),
):
    """固定奖级口径下的预算模拟（展示亏损分布，不展示预期盈利）。"""
    code = (game or "").strip().lower()
    if registry.get_game(code) is None:
        raise HTTPException(status_code=404, detail="未找到该彩票游戏")
    try:
        result = lab.simulate_budget(
            code, periods=periods, tickets_per_period=tickets
        )
    except lab.LabDataError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    result["note"] = f"{result['note']}{_COMMON_NOTE}"
    return result


class InterpretRequest(BaseModel):
    game: str
    window: int = Field(default=100, ge=lab.MIN_SAMPLE, le=200)
    periods: int = Field(default=100, ge=1, le=520)
    tickets: int = Field(default=1, ge=1, le=20)
    include_budget: bool = True


@router.get("/llm/status")
def lab_llm_status():
    """AI 解读是否已配置；不返回任何密钥。"""
    return llm.public_status()


@router.post("/interpret")
def lab_interpret(
    payload: InterpretRequest,
    user: dict = Depends(get_current_user),
):
    """登录后按当前统计结果生成 AI 解读（按用户限流）。"""
    code = (payload.game or "").strip().lower()
    if registry.get_game(code) is None:
        raise HTTPException(status_code=404, detail="未找到该彩票游戏")
    if code not in lab.PROFILES:
        raise HTTPException(
            status_code=400,
            detail="该游戏暂不支持历史数据分析，仅支持数字型号码游戏",
        )
    if not llm.is_configured():
        raise HTTPException(status_code=503, detail="AI 解读尚未配置，请联系站点管理员")

    allowed, retry_after = LIMITER.allow(
        f"lab-llm:{user['id']}",
        config.LLM_RATE_LIMIT,
        config.LLM_RATE_WINDOW_SECONDS,
    )
    if not allowed:
        raise HTTPException(
            status_code=429,
            detail=f"生成太频繁，请 {retry_after} 秒后再试",
            headers={"Retry-After": str(retry_after)},
        )

    try:
        analysis = lab.analyze(code, window=payload.window)
    except lab.LabDataError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    budget = None
    if payload.include_budget and analysis["game"]["budget_supported"]:
        try:
            budget = lab.simulate_budget(
                code, periods=payload.periods, tickets_per_period=payload.tickets
            )
        except lab.LabDataError:
            budget = None

    try:
        result = llm.request_interpretation(analysis, budget)
    except llm.LLMNotConfigured as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except llm.LLMError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    result.update(
        {
            "game": {
                "code": analysis["game"]["code"],
                "name": analysis["game"]["name"],
            },
            "window_used": analysis["window_used"],
            "notice": (
                "AI 生成内容可能有误，只是对历史统计的通俗解释；"
                "不预测开奖、不推荐号码，也不构成投注建议。"
            ),
        }
    )
    return result
