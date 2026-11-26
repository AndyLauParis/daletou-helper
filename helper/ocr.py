"""票面识别（OpenAI 兼容视觉接口）。

只负责把票面图片转成结构化候选数据；号码合法性、去重与状态标记
统一交给 `helper.recognition` 处理。
"""

from __future__ import annotations

import base64
import json
import logging
import re
import urllib.error
import urllib.request
from urllib.parse import urlsplit

from . import config, ticket_parse

logger = logging.getLogger("helper.ocr")

MAX_RAW_TEXT = 2000

# 视觉识别支持的号码型游戏：game_code -> (名称, payload 结构示例与玩法要求)
OCR_GAMES: dict[str, tuple[str, str]] = {
    "dlt": (
        "超级大乐透",
        'payload 形如 {"front": ["01","07","12","23","35"], "back": ["03","11"]}',
    ),
    "ssq": (
        "双色球",
        'payload 形如 {"red": ["01","02","03","04","05","06"], "blue": ["07"]}',
    ),
    "fc3d": (
        "福彩3D",
        'payload 形如 {"digits": "123"}；play_type 为 zhixuan、zu3 或 zu6',
    ),
    "pl3": (
        "排列3",
        'payload 形如 {"digits": "123"}；play_type 必须为 zhixuan、zu3 或 zu6',
    ),
    "pl5": ("排列5", 'payload 形如 {"digits": "12345"}'),
    "qxc": ("七星彩", 'payload 形如 {"front": "123456", "back": "7"}'),
    "qlc": (
        "七乐彩",
        'payload 形如 {"basic": ["01","02","03","04","05","06","07"]}',
    ),
    "kl8": (
        "快乐8",
        'payload 形如 {"picks": ["01","05","10"]}（1-10 个号码）；play_type 为 selectN',
    ),
}

SYSTEM_PROMPT = """你是彩票票面识别器。请从用户上传的彩票图片中识别投注号码、期号与玩法，并且只输出一个 JSON 对象，不要输出解释、Markdown 或代码块。

输出字段：
- game_code：彩票类型代码，只能从下面的列表中选择。
- issue：期号，纯数字字符串；无法确认时为空字符串。
- play_type：玩法代码；没有玩法概念时为 null。
- payload：号码结构，严格按该游戏的格式说明填写，号码统一用两位字符串。
- confidence：0 到 1 的总体置信度。
- field_confidence：形如 {"game_code":0.9,"issue":0.9,"payload":0.8} 的分项置信度。
- ticket_no：票号或校验码，没有则为 null。
- raw_text：图片中与识别相关的关键文字，最多 200 字。

如果图片不是彩票、模糊不可读或无法判断彩票类型，返回 {"game_code": null}。不得编造号码；不确定的号码降低置信度。"""


class OcrError(RuntimeError):
    """识别服务调用失败。"""


class OcrNotConfigured(OcrError):
    """未配置视觉识别接口。"""


def is_configured() -> bool:
    return bool(config.OCR_BASE_URL and config.OCR_API_KEY and config.OCR_MODEL)


def public_status() -> dict:
    """供前端展示，不包含密钥。"""
    return {
        "enabled": is_configured(),
        "mode": config.OCR_MODE,
        "provider": config.OCR_PROVIDER,
        "model": config.OCR_MODEL if is_configured() else "",
        "threshold": config.OCR_CONFIDENCE_THRESHOLD,
        "max_image_bytes": config.OCR_MAX_IMAGE_BYTES,
        "supported_games": [
            {"code": code, "name": name} for code, (name, _) in OCR_GAMES.items()
        ],
    }


def _endpoint(base_url: str) -> str:
    base = (base_url or "").strip().rstrip("/")
    if base.endswith("/chat/completions"):
        return base
    return base + "/chat/completions"


def _document_parse_endpoint(base_url: str) -> str:
    base = (base_url or "").strip().rstrip("/")
    if base.endswith("/document-parse"):
        return base
    return base + "/document-parse"


def _error_for_status(status: int) -> str:
    if status in (401, 403):
        return "识别服务鉴权失败，请检查 OCR API Key"
    if status == 402:
        return "识别服务账户余额不足"
    if status == 404:
        return "识别服务地址或模型名不正确"
    if status in (400, 422):
        return "识别服务拒绝了请求，请确认已配置支持图片输入的视觉模型"
    if status == 429:
        return "识别服务限流或额度已用尽，请稍后再试"
    if status >= 500:
        return "识别服务暂时不可用，请稍后再试"
    return f"识别服务调用失败（HTTP {status}）"


def _extract_text(data: dict) -> str:
    choices = data.get("choices") or []
    if not choices:
        return ""
    content = (choices[0].get("message") or {}).get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(
            part.get("text", "")
            for part in content
            if isinstance(part, dict) and isinstance(part.get("text"), str)
        )
    return ""


def _parse_json_object(text: str) -> dict:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```[a-zA-Z]*\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", cleaned, re.S)
        if not match:
            raise OcrError("识别结果不是合法 JSON")
        try:
            data = json.loads(match.group(0))
        except json.JSONDecodeError as exc:
            raise OcrError("识别结果不是合法 JSON") from exc
    if not isinstance(data, dict):
        raise OcrError("识别结果格式异常")
    return data


def _clamp(value) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(1.0, number))


def _build_messages(game_hint: str | None) -> tuple[str, str]:
    lines = [SYSTEM_PROMPT, "", "可选彩票类型："]
    for code, (name, schema) in OCR_GAMES.items():
        lines.append(f"- {code}（{name}）：{schema}")
    user_text = "请识别这张彩票，并按系统要求输出 JSON。"
    if game_hint and game_hint in OCR_GAMES:
        name = OCR_GAMES[game_hint][0]
        user_text = f"用户提示彩票类型为 {game_hint}（{name}）。请核对图片，按系统要求输出 JSON。"
    return "\n".join(lines), user_text


def _post_json(url: str, payload: dict) -> dict:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Authorization": f"Bearer {config.OCR_API_KEY}",
            "User-Agent": "helper-ocr/1.0",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=config.OCR_TIMEOUT_SECONDS) as resp:
            raw = resp.read()
    except urllib.error.HTTPError as exc:
        logger.warning("票面识别请求失败：status=%s", exc.code)
        raise OcrError(_error_for_status(exc.code)) from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        logger.warning("票面识别请求异常：%s", type(exc).__name__)
        raise OcrError("无法连接票面识别服务，请稍后再试") from exc

    try:
        return json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        logger.warning("票面识别返回内容不是合法 JSON")
        raise OcrError("识别服务返回格式异常") from exc


def _ocr_text_from_response(data: dict) -> str:
    """ModelBest/MiniCPM-OCR：优先按 blocks 顺序拼接，其次用 content。"""
    blocks = (data.get("ocr") or {}).get("blocks") or []
    contents = []
    for block in sorted(
        (block for block in blocks if isinstance(block, dict)),
        key=lambda block: block.get("order", 0),
    ):
        text = block.get("content")
        if isinstance(text, str) and text.strip():
            contents.append(text.strip())
    if contents:
        return "\n".join(contents)
    return _extract_text(data)


def _recognize_openai(data_url: str, hint: str | None) -> dict:
    system_text, user_text = _build_messages(hint)
    body = _post_json(
        _endpoint(config.OCR_BASE_URL),
        {
            "model": config.OCR_MODEL,
            "messages": [
                {"role": "system", "content": system_text},
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": user_text},
                        {"type": "image_url", "image_url": {"url": data_url}},
                    ],
                },
            ],
            "temperature": 0,
            "max_tokens": 900,
            "stream": False,
        },
    )
    result = _parse_json_object(_extract_text(body))
    game_code = str(result.get("game_code") or hint or "").strip().lower()
    if game_code not in OCR_GAMES:
        raise OcrError("未能识别彩票类型，请换一张更清晰的照片或手动选择类型")

    number_payload = result.get("payload")
    if number_payload is None:
        number_payload = result.get("numbers")
    if number_payload is None:
        raise OcrError("未能从图片中识别出号码")

    field_confidence = result.get("field_confidence")
    if not isinstance(field_confidence, dict):
        field_confidence = {}

    logger.info(
        "票面识别完成(openai)：game=%s issue=%s confidence=%.2f",
        game_code,
        str(result.get("issue") or "")[:16],
        _clamp(result.get("confidence")),
    )
    return {
        "game_code": game_code,
        "issue": str(result.get("issue") or "").strip(),
        "play_type": result.get("play_type"),
        "payload": number_payload,
        "confidence": _clamp(result.get("confidence")),
        "field_confidence": {
            str(key)[:32]: _clamp(value) for key, value in field_confidence.items()
        },
        "ticket_no": str(result.get("ticket_no") or "").strip()[:64] or None,
        "raw_text": str(result.get("raw_text") or "").strip()[:MAX_RAW_TEXT],
        "model": config.OCR_MODEL,
        "provider": config.OCR_PROVIDER,
    }


def _recognize_modelbest(data_url: str, hint: str | None) -> dict:
    body = _post_json(
        _document_parse_endpoint(config.OCR_BASE_URL),
        {
            "model": config.OCR_MODEL,
            "image": data_url,
            "upright": True,
            "recognize_seal": True,
        },
    )
    text = _ocr_text_from_response(body)
    try:
        result = ticket_parse.parse_ticket_text(
            text,
            hint,
            model=config.OCR_MODEL,
            provider=config.OCR_PROVIDER,
        )
    except ticket_parse.TicketParseError as exc:
        raise OcrError(str(exc)) from exc
    logger.info(
        "票面识别完成(modelbest)：game=%s issue=%s confidence=%.2f text_chars=%s",
        result["game_code"],
        str(result.get("issue") or "")[:16],
        result["confidence"],
        len(text),
    )
    return result


def recognize_ticket(
    image_bytes: bytes, mime: str, game_hint: str | None = None
) -> dict:
    """调用视觉接口识别单张彩票；失败时抛出 OcrError。"""
    if not is_configured():
        raise OcrNotConfigured(
            "票面识别服务尚未配置。请设置 HELPER_OCR_BASE_URL、HELPER_OCR_API_KEY "
            "与 HELPER_OCR_MODEL（需支持图片输入）。"
        )

    parsed = urlsplit(config.OCR_BASE_URL)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise OcrNotConfigured("HELPER_OCR_BASE_URL 不是有效的 http(s) 地址")

    hint = (game_hint or "").strip().lower() or None
    data_url = f"data:{mime};base64,{base64.b64encode(image_bytes).decode('ascii')}"
    if config.OCR_MODE in {"modelbest", "minicpm", "document_parse"}:
        return _recognize_modelbest(data_url, hint)
    return _recognize_openai(data_url, hint)
