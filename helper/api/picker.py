"""娱乐选号 API：按组合规则生成号码，不预测开奖。"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from .. import picker
from ..games import registry

router = APIRouter(prefix="/api/helper/picker", tags=["picker"])


class GenerateRequest(BaseModel):
    game: str
    method: str = "random"
    tickets: int = Field(default=1, ge=1, le=10)


@router.get("/options")
def picker_options():
    """可选游戏与选号方式。"""
    return picker.options()


@router.post("/generate")
def picker_generate(payload: GenerateRequest):
    """按所选方式生成号码组合；结果仅用于娱乐。"""
    code = (payload.game or "").strip().lower()
    if registry.get_game(code) is None:
        raise HTTPException(status_code=404, detail="未找到该彩票游戏")
    try:
        return picker.generate(code, payload.method, payload.tickets)
    except picker.PickerError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
