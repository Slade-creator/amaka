"""Unit smoke tests for the grounded chart narrative (no network required).

Covers:
  - fact-pack construction and clamping for every site / horizon / role;
  - deterministic fallback text and rule-based Q&A grounding;
  - the model path with a stubbed provider, including the cache;
  - rejection of hallucinated numbers and forbidden vocabulary;
  - the "no model configured" path.

Usage:
    python tests/smoke_narrate.py
"""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pandas as pd  # noqa: E402

from backend import narrate, store  # noqa: E402

SITES = ["arakan", "kohima", "makeni", "mikango", "peter_zuze", "tug_argan"]
HORIZONS = [1, 6, 24, 48]
ROLES = ["commander", "operator", "analyst"]
ANCHOR = pd.Timestamp("2025-09-09T18:00:00")
QUESTIONS = [
    "Why did load peak?",
    "How accurate was the forecast?",
    "Was there a readiness surge?",
    "What were the top drivers?",
    "How much headroom is there?",
    "What was the weather?",
    "What was the trend?",
    "What was the average load?",
]


def check(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)
    print(f"  ok  {message}")


def reset_model_state() -> None:
    narrate._CACHE.clear()
    narrate._BREAKER.update({"failures": 0, "open_until": 0.0, "last_error": ""})


def test_provider_config() -> None:
    print("\nprovider configuration")
    keys = ("SENTINEL_LLM_PROVIDER", "SENTINEL_LLM_BASE_URL",
            "SENTINEL_LLM_MODEL", "OPENAI_BASE_URL")
    saved = {k: os.environ.get(k) for k in keys}
    try:
        os.environ.pop("SENTINEL_LLM_BASE_URL", None)
        os.environ.pop("SENTINEL_LLM_MODEL", None)
        os.environ["OPENAI_BASE_URL"] = "https://openrouter.ai/api/v1"
        os.environ["SENTINEL_LLM_PROVIDER"] = "ollama"
        cfg = narrate.llm_config()
        check(cfg.base_url == "http://127.0.0.1:11434",
              "ollama ignores a leftover OPENAI_BASE_URL")
        check(cfg.available, "ollama needs no API key")

        os.environ["SENTINEL_LLM_PROVIDER"] = "openrouter"
        check(narrate.llm_config().base_url
              == "https://openrouter.ai/api/v1",
              "openrouter uses OPENAI_BASE_URL when it is set")

        os.environ["SENTINEL_LLM_PROVIDER"] = "off"
        check(not narrate.llm_config().available,
              "provider off is not available")
    finally:
        for key, value in saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def test_facts_and_fallback() -> None:
    print("\nfact pack + deterministic fallback")
    for site in SITES:
        for horizon in HORIZONS:
            for role in ROLES:
                facts = narrate.build_facts(site, horizon, ANCHOR, None, None, role)
                check(facts["site"]["id"] == site, f"{site} h={horizon} {role}: site id")
                check(facts["forecast_horizon_hours"] == horizon,
                      f"{site} h={horizon} {role}: horizon")
                check(facts["window"]["hours"] > 0,
                      f"{site} h={horizon} {role}: window has rows")
                check(facts["selected_hour"]["timestamp"] == ANCHOR.isoformat(),
                      f"{site} h={horizon} {role}: selected hour")
                text = narrate._fallback_text(facts)
                check(len(text.split()) >= 40,
                      f"{site} h={horizon} {role}: fallback is substantial")
                try:
                    narrate._grounded(text, facts)
                except narrate.GroundingError as exc:
                    raise AssertionError(
                        f"{site} h={horizon} {role}: fallback not grounded: {exc}"
                    ) from exc
                check(True, f"{site} h={horizon} {role}: fallback passes grounding")


def test_rule_answers() -> None:
    print("\nrule-based Q&A")
    for role in ROLES:
        facts = narrate.build_facts("peter_zuze", 24, ANCHOR, None, None, role)
        for question in QUESTIONS:
            answer = narrate._rule_answer(question, facts)
            try:
                narrate._grounded(answer, facts, question)
            except narrate.GroundingError as exc:
                raise AssertionError(f"{question!r} ({role}): {exc}") from exc
            check(True, f"{role}: {question} -> grounded")


def _good_text(facts: dict) -> str:
    s = facts["selected_hour"]
    w = facts["window"]
    return (
        f"On {narrate._when(s['timestamp'])}, actual load was "
        f"{narrate._kw(s['actual_kw'])} against a "
        f"{narrate._kw(s['forecast_kw'])} forecast. The site was at "
        f"{s['readiness']}. Over {w['hours']} hours, load peaked at "
        f"{narrate._kw(w['actual_max_kw'])}."
    )


def test_model_path() -> None:
    print("\nmodel path (stubbed provider)")
    os.environ["SENTINEL_LLM_PROVIDER"] = "openai"
    os.environ["SENTINEL_LLM_API_KEY"] = "test-key"
    reset_model_state()

    facts = narrate.build_facts("peter_zuze", 24, ANCHOR, None, None, "operator")
    good = _good_text(facts)

    async def fake(messages, cfg):
        return good

    original = narrate._call_llm
    narrate._call_llm = fake
    try:
        first = asyncio.run(narrate.narrative(
            "peter_zuze", 24, ANCHOR, None, None, "operator", True))
        check(first["source"] == "model", "valid model prose is accepted")
        check(first["cached"] is False, "first model call is not cached")

        second = asyncio.run(narrate.narrative(
            "peter_zuze", 24, ANCHOR, None, None, "operator", True))
        check(second["source"] == "model" and second["cached"] is True,
              "repeat request hits the model cache")

        narrate._CACHE.clear()

        async def hallucinate(messages, cfg):
            return good + " The peak was 99,999 kW."

        narrate._call_llm = hallucinate
        bad = asyncio.run(narrate.narrative(
            "peter_zuze", 24, ANCHOR, None, None, "operator", True))
        check(bad["source"] == "rules", "hallucinated number falls back")
        check(bad["fallback_reason"] == "grounding",
              "fallback reason is 'grounding'")
        check(bad["text"] == narrate._fallback_text(facts),
              "grounding failure returns the deterministic text")

        narrate._CACHE.clear()

        async def forbidden(messages, cfg):
            return good + " This is a prediction of the facility."

        narrate._call_llm = forbidden
        blocked = asyncio.run(narrate.narrative(
            "peter_zuze", 24, ANCHOR, None, None, "operator", True))
        check(blocked["source"] == "rules", "forbidden vocabulary falls back")
        check(blocked["fallback_reason"] == "grounding",
              "forbidden vocabulary is a grounding failure")

        narrate._CACHE.clear()

        async def ask_fake(messages, cfg):
            return (f"Forecast error averaged "
                    f"{narrate._pct(facts['window']['mape_pct'])} over the window.")

        narrate._call_llm = ask_fake
        answer = asyncio.run(narrate.answer(
            "peter_zuze", 24, ANCHOR, None, None, "analyst",
            "How accurate was the forecast?"))
        check(answer["source"] == "model", "question path accepts grounded prose")
    finally:
        narrate._call_llm = original


def test_no_model() -> None:
    print("\nno model configured")
    os.environ["SENTINEL_LLM_PROVIDER"] = "off"
    reset_model_state()
    result = asyncio.run(narrate.narrative(
        "arakan", 24, ANCHOR, None, None, "operator", True))
    check(result["source"] == "rules", "provider off returns rules")
    check(result["fallback_reason"] == "not_configured",
          "provider off reports not_configured")
    check(bool(result["notice"]), "provider off explains the fallback")

    answer = asyncio.run(narrate.answer(
        "arakan", 24, ANCHOR, None, None, "operator", "What was the peak?"))
    check(answer["source"] == "rules", "question with provider off returns rules")
    check(bool(answer["answer"]), "question fallback still answers")


def main() -> int:
    check(narrate.normalize_role("ops") == "operator", "role alias 'ops'")
    check(narrate.normalize_mode("fast") == "fast", "mode 'fast'")
    try:
        narrate.normalize_role("nope")
    except ValueError:
        check(True, "unknown role is rejected")
    else:
        raise AssertionError("unknown role should raise")

    test_provider_config()
    test_facts_and_fallback()
    test_rule_answers()
    test_model_path()
    test_no_model()
    print("\nALL NARRATIVE CHECKS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
