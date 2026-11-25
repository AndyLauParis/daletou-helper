"""大模型辅助解读（OpenAI 兼容接口）。

只把实验室已经算好的统计摘要交给模型，让模型用通俗语言解释随机性；
提示词明确禁止预测号码、推荐号码或暗示可以提高中奖概率。
"""

from __future__ import annotations

import json
import logging
import re
import time
import urllib.error
import urllib.request
from collections import OrderedDict
from datetime import datetime
from threading import Lock
from urllib.parse import urlsplit

from . import config

logger = logging.getLogger("helper.llm")

CACHE_TTL_SECONDS = 60 * 60
CACHE_MAX_ENTRIES = 32
MAX_TEXT_CHARS = 8000

SYSTEM_PROMPT = """你是彩票历史数据的统计解释助手。你的唯一任务是解释用户提供的统计结果，帮助读者理解随机性和常见误读。

必须遵守以下规则：
1. 不得预测、暗示或推荐任何未来开奖号码；不要出现“下期可能”“值得关注”“可以选”“建议购买”等表述。
2. 不得声称历史数据、冷热号、遗漏或回测能提高中奖概率，也不得把 p 值小于 0.05 解释为存在可利用规律。
3. 只能引用用户消息中给出的数字，不得编造、估算或补充未提供的统计量。
4. 必须说明样本量、抽样波动和多重比较的影响：本页同时做 5 项随机性检验，即使开奖完全随机，出现至少一个 p 值小于 0.05 的概率也约为 23%。
5. 使用中文纯文本，按“结论 / 关键数据 / 常见误读 / 风险提示”四个短段落输出，总字数控制在 350–600 字，不要使用 Markdown 加粗、标题、表格或代码块。
6. 最后一句必须是：“以上仅是对历史样本的统计解释，不预测未来开奖，也不构成投注建议。”"""

_CACHE: "OrderedDict[tuple, dict]" = OrderedDict()
_CACHE_LOCK = Lock()


class LLMError(RuntimeError):
    """大模型调用失败（配置、网络或上游返回异常）。"""


class LLMNotConfigured(LLMError):
    """未配置 Base URL、API Key 或模型名。"""


def is_configured() -> bool:
    return bool(config.LLM_BASE_URL and config.LLM_API_KEY and config.LLM_MODEL)


def public_status() -> dict:
    """供前端展示的配置状态，不包含密钥。"""
    return {
        "enabled": is_configured(),
        "provider": config.LLM_PROVIDER,
        "model": config.LLM_MODEL if is_configured() else "",
        "notice": (
            "AI 解读只解释历史统计，不预测开奖、不推荐号码；"
            "生成内容可能有误，请以本页统计与官方开奖为准。"
        ),
    }


def clear_cache() -> None:
    with _CACHE_LOCK:
        _CACHE.clear()


def _num(value, digits: int = 2) -> str:
    try:
        return f"{float(value):.{digits}f}"
    except (TypeError, ValueError):
        return "—"


def _frequency_lines(analysis: dict) -> list[str]:
    lines: list[str] = []
    for group in analysis.get("frequency") or []:
        rows = [row for row in group.get("numbers") or [] if row]
        if not rows:
            continue
        label = group.get("label") or group.get("key") or "号码"
        expected = rows[0].get("expected_rate")
        top = sorted(rows, key=lambda row: (-row.get("count", 0), row.get("number", 0)))[:3]
        low = sorted(rows, key=lambda row: (row.get("count", 0), row.get("number", 0)))[:3]
        omitted = sorted(
            rows, key=lambda row: (-row.get("current_omission", 0), row.get("number", 0))
        )[:3]
        lines.append(
            f"- {label}（{group.get('pool')} 选 {group.get('pick')}，单号理论出现率 "
            f"{_num(row_pct(expected), 1)}%）：出现最多 "
            + "、".join(
                f"{row.get('number')}（{row.get('count')} 次）" for row in top
            )
            + "；出现最少 "
            + "、".join(
                f"{row.get('number')}（{row.get('count')} 次）" for row in low
            )
            + "；当前遗漏最大 "
            + "、".join(
                f"{row.get('number')}（{row.get('current_omission')} 期）"
                for row in omitted
            )
        )
    return lines


def row_pct(rate) -> float:
    try:
        return float(rate) * 100
    except (TypeError, ValueError):
        return 0.0


def _shape_lines(analysis: dict) -> list[str]:
    shape = analysis.get("shape") or {}
    lines: list[str] = []
    summary = shape.get("sum") or {}
    if summary:
        lines.append(
            f"- 和值：均值 {_num(summary.get('mean'))}（理论 {_num(summary.get('theoretical_mean'))}），"
            f"标准差 {_num(summary.get('stdev'))}，最小 {summary.get('min')}，最大 {summary.get('max')}。"
        )
    odd = shape.get("odd") or {}
    if odd:
        lines.append(
            f"- 奇数个数：均值 {_num(odd.get('mean'))}（理论 {_num(odd.get('theoretical_mean'))}）。"
        )
    repeat = shape.get("repeat") or {}
    if repeat:
        lines.append(
            f"- 相邻期重号：均值 {_num(repeat.get('mean'))}（理论 {_num(repeat.get('theoretical_mean'))}）。"
        )
    zones = shape.get("zones") or []
    if zones:
        lines.append(
            "- 三区每期平均个数："
            + "；".join(
                f"{zone.get('label')} {_num(zone.get('avg'))} 个（期望 {_num(zone.get('expected'))}）"
                for zone in zones
            )
            + "。"
        )
    consecutive = shape.get("consecutive")
    if consecutive:
        lines.append(f"- 连号对数：均值 {_num(consecutive.get('mean'))}。")
    return lines


def _test_lines(analysis: dict) -> list[str]:
    randomness = analysis.get("randomness") or {}
    lines = [
        f"- {test.get('label')}：观测 {_num(test.get('observed'), 4)}，"
        f"随机均值 {_num(test.get('null_mean'), 4)}，"
        f"90% 随机区间 {_num(test.get('null_p05'), 4)}–{_num(test.get('null_p95'), 4)}，"
        f"经验 p 值 {_num(test.get('p_value'), 4)}，结论：{test.get('verdict')}"
        for test in randomness.get("tests") or []
    ]
    if lines:
        lines.insert(
            0,
            f"随机性检验（共 {len(lines)} 项，蒙特卡洛 {randomness.get('trials')} 次）：",
        )
    return lines


def _backtest_lines(analysis: dict) -> list[str]:
    backtest = analysis.get("backtest") or {}
    strategies = backtest.get("strategies") or []
    if not strategies:
        return []
    lines = [
        f"选号方式回测（最近 {backtest.get('test_size')} 期，每期使用此前 "
        f"{backtest.get('lookback')} 期，理论期望命中 {_num(backtest.get('expected_hits'), 3)}）："
    ]
    for strategy in strategies:
        lines.append(
            f"- {strategy.get('label')}：平均命中 {_num(strategy.get('avg_hits'), 3)}，"
            f"与理论期望相差 {_num(strategy.get('diff_from_expected'), 3)}，"
            f"最高命中 {strategy.get('max_hits')}。"
        )
    return lines


def _budget_lines(budget: dict | None) -> list[str]:
    if not budget:
        return []
    percentiles = budget.get("net_percentiles") or {}
    lines = [
        f"预算模拟（{budget.get('periods')} 期 × 每期 {budget.get('tickets_per_period')} 注，"
        f"累计投入 {_num(budget.get('spend'))} 元，共模拟 {budget.get('trials')} 次）：",
        f"- 平均返奖 {_num(budget.get('avg_return'))} 元，"
        f"平均净收益（返奖减投入） {_num(budget.get('avg_net'))} 元，"
        f"亏损概率 {_num(row_pct(budget.get('p_loss')), 1)}%，"
        f"保本概率 {_num(row_pct(budget.get('p_even')), 1)}%，"
        f"盈利概率 {_num(row_pct(budget.get('p_profit')), 1)}%。",
        f"- 净支出分位：5% {_num(percentiles.get('p05'))}，"
        f"25% {_num(percentiles.get('p25'))}，50% {_num(percentiles.get('p50'))}，"
        f"75% {_num(percentiles.get('p75'))}，95% {_num(percentiles.get('p95'))} 元。",
    ]
    distribution = budget.get("distribution") or []
    if distribution:
        lines.append(
            "- 返奖占投入比例："
            + "；".join(
                f"{row.get('label')} {_num(row_pct(row.get('share')), 1)}%"
                for row in distribution
            )
            + "。"
        )
    lines.append("- 模拟只计入官方固定奖级，不含浮动奖与追加投注。")
    return lines


def build_messages(analysis: dict, budget: dict | None = None) -> list[dict]:
    """把统计结果压缩成提示词；不包含任何用户自由文本。"""
    game = analysis.get("game") or {}
    date_range = analysis.get("date_range") or {}
    lines = [
        f"游戏：{game.get('name')}（{game.get('format_summary')}）",
        f"样本：最近 {analysis.get('window_used')} 期"
        f"（{date_range.get('from')} 至 {date_range.get('to')}），"
        f"本地可用 {analysis.get('available_draws')} 期，最新期号 {analysis.get('latest_issue')}。",
    ]
    frequency = _frequency_lines(analysis)
    if frequency:
        lines.append("号码频次与遗漏（仅描述历史样本，不代表未来）：")
        lines.extend(frequency)
    shape = _shape_lines(analysis)
    if shape:
        lines.append("形态统计：")
        lines.extend(shape)
    lines.extend(_test_lines(analysis))
    lines.extend(_backtest_lines(analysis))
    lines.extend(_budget_lines(budget))
    lines.append(
        "请基于以上数字写一段通俗解读，重点说明这些差异为什么不能用于预测，"
        "以及读者最容易产生哪些误解。不要给出任何号码或购买建议。"
    )
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": "\n".join(lines)},
    ]


def _endpoint(base_url: str) -> str:
    base = (base_url or "").strip().rstrip("/")
    if base.endswith("/chat/completions"):
        return base
    return base + "/chat/completions"


def _extract_text(data: dict) -> str:
    choices = data.get("choices") or []
    if not choices:
        return ""
    message = choices[0].get("message") or {}
    content = message.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for part in content:
            if isinstance(part, dict) and isinstance(part.get("text"), str):
                parts.append(part["text"])
        return "".join(parts)
    return ""


def _plain_text(text: str) -> str:
    """去掉模型偶尔带出的 Markdown 加粗与标题符号。"""
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
    text = re.sub(r"(?m)^#{1,6}\s*", "", text)
    return text.strip()


def _error_for_status(status: int) -> str:
    if status in (401, 403):
        return "大模型接口鉴权失败，请检查 API Key"
    if status == 402:
        return "大模型账户余额不足"
    if status == 404:
        return "大模型接口地址或模型名不正确"
    if status == 429:
        return "大模型接口限流或额度已用尽，请稍后再试"
    if status >= 500:
        return "大模型服务暂时不可用，请稍后再试"
    return f"大模型调用失败（HTTP {status}）"


def _cache_key(analysis: dict, budget: dict | None) -> tuple:
    game = analysis.get("game") or {}
    budget_key = None
    if budget:
        budget_key = (
            budget.get("periods"),
            budget.get("tickets_per_period"),
            budget.get("spend"),
            budget.get("trials"),
        )
    return (
        game.get("code"),
        analysis.get("window_used"),
        analysis.get("latest_issue"),
        budget_key,
    )


def request_interpretation(analysis: dict, budget: dict | None = None) -> dict:
    """调用 OpenAI 兼容接口生成解读；失败时抛出 LLMError。"""
    if not is_configured():
        raise LLMNotConfigured(
            "AI 解读尚未配置。请设置 HELPER_LLM_BASE_URL、HELPER_LLM_API_KEY 与 HELPER_LLM_MODEL。"
        )

    parsed = urlsplit(config.LLM_BASE_URL)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise LLMNotConfigured("HELPER_LLM_BASE_URL 不是有效的 http(s) 地址")

    key = _cache_key(analysis, budget)
    now = time.monotonic()
    with _CACHE_LOCK:
        cached = _CACHE.get(key)
        if cached and now - cached["_stored"] <= CACHE_TTL_SECONDS:
            _CACHE.move_to_end(key)
            result = {k: v for k, v in cached.items() if k != "_stored"}
            result["cached"] = True
            return result

    messages = build_messages(analysis, budget)
    payload = {
        "model": config.LLM_MODEL,
        "messages": messages,
        "temperature": 0.3,
        "max_tokens": config.LLM_MAX_TOKENS,
        "stream": False,
    }
    request = urllib.request.Request(
        _endpoint(config.LLM_BASE_URL),
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Authorization": f"Bearer {config.LLM_API_KEY}",
            "User-Agent": "helper-llm/1.0",
        },
    )

    started = time.monotonic()
    try:
        with urllib.request.urlopen(request, timeout=config.LLM_TIMEOUT_SECONDS) as resp:
            raw = resp.read()
    except urllib.error.HTTPError as exc:
        logger.warning("大模型请求失败：status=%s", exc.code)
        raise LLMError(_error_for_status(exc.code)) from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        logger.warning("大模型请求异常：%s", type(exc).__name__)
        raise LLMError("无法连接大模型服务，请检查接口地址或稍后再试") from exc

    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        logger.warning("大模型返回内容不是合法 JSON")
        raise LLMError("大模型返回格式异常，请稍后再试") from exc

    text = _plain_text(_extract_text(data))
    if not text:
        raise LLMError("大模型返回了空内容，请稍后再试")
    if len(text) > MAX_TEXT_CHARS:
        text = text[:MAX_TEXT_CHARS].rstrip() + "…"

    usage = data.get("usage") if isinstance(data.get("usage"), dict) else {}
    elapsed = time.monotonic() - started
    logger.info(
        "大模型解读完成：model=%s prompt_chars=%s completion_tokens=%s elapsed=%.2fs",
        data.get("model") or config.LLM_MODEL,
        len(messages[1]["content"]),
        usage.get("completion_tokens"),
        elapsed,
    )

    result = {
        "text": text,
        "model": str(data.get("model") or config.LLM_MODEL),
        "provider": config.LLM_PROVIDER,
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "cached": False,
    }
    with _CACHE_LOCK:
        _CACHE[key] = {**result, "_stored": time.monotonic()}
        _CACHE.move_to_end(key)
        while len(_CACHE) > CACHE_MAX_ENTRIES:
            _CACHE.popitem(last=False)
    return result
