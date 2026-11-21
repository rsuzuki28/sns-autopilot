"""Claude API 呼び出しの共通処理。"""
from __future__ import annotations

import json

import anthropic

from .config import load_account

FALLBACK_BETA = "server-side-fallback-2026-07-01"


class LLMError(RuntimeError):
    pass


def _client() -> anthropic.Anthropic:
    return anthropic.Anthropic()


def _call(messages: list, system: str, *, tools=None, output_config=None) -> anthropic.types.beta.BetaMessage:
    cfg = load_account()["llm"]
    oc = {"effort": cfg.get("effort", "high")}
    if output_config:
        oc.update(output_config)
    kwargs = dict(
        model=cfg.get("model", "claude-opus-5-5"),
        max_tokens=64000,
        system=system,
        messages=messages,
        thinking={"type": "adaptive"},
        output_config=oc,
        # 安全分類器に誤って断られた場合、サーバー側で別モデルに自動で切り替える
        betas=[FALLBACK_BETA],
        fallbacks="default",
    )
    if tools:
        kwargs["tools"] = tools
    with _client().beta.messages.stream(**kwargs) as stream:
        return stream.get_final_message()


def _text_of(msg) -> str:
    return "".join(b.text for b in msg.content if b.type == "text")


def _check(msg) -> None:
    if msg.stop_reason == "refusal":
        cat = getattr(msg.stop_details, "category", None) if msg.stop_details else None
        raise LLMError(f"Claudeが応答を拒否しました (category={cat})")
    if msg.stop_reason == "max_tokens":
        raise LLMError("出力が上限に達しました")


def research(system: str, prompt: str) -> str:
    """Web検索つきでリサーチし、テキストを返す。"""
    cfg = load_account()["llm"]
    tools = [{
        "type": "web_search_20260209",
        "name": "web_search",
        "max_uses": int(cfg.get("web_search_max_uses", 8)),
        "user_location": {"type": "approximate", "country": "JP", "timezone": "Asia/Tokyo"},
    }]
    messages = [{"role": "user", "content": prompt}]
    for _ in range(6):
        msg = _call(messages, system, tools=tools)
        if msg.stop_reason == "pause_turn":
            messages.append({"role": "assistant", "content": msg.content})
            continue
        _check(msg)
        return _text_of(msg)
    raise LLMError("リサーチが終わりませんでした（pause_turnの繰り返し）")


def generate_json(system: str, prompt: str, schema: dict) -> dict:
    """JSONスキーマ通りの出力を返す。"""
    msg = _call(
        [{"role": "user", "content": prompt}],
        system,
        output_config={"format": {"type": "json_schema", "schema": schema}},
    )
    _check(msg)
    return json.loads(_text_of(msg))


def generate_text(system: str, prompt: str) -> str:
    msg = _call([{"role": "user", "content": prompt}], system)
    _check(msg)
    return _text_of(msg)
