import json
import re
import time
from typing import Optional

from openai import OpenAI, APIError, APITimeoutError, RateLimitError

from .logging import get_logger

logger = get_logger("llm")


def _extract_json_object(text: str) -> Optional[dict]:
    """扫描文本，依次尝试每个 { 位置，找到第一个合法 JSON 对象"""
    for start in range(len(text)):
        if text[start] != '{':
            continue
        depth = 0
        for end in range(start, len(text)):
            ch = text[end]
            if ch == '{':
                depth += 1
            elif ch == '}':
                depth -= 1
                if depth == 0:
                    candidate = text[start:end + 1]
                    try:
                        return json.loads(candidate)
                    except json.JSONDecodeError:
                        break  # balanced but invalid JSON, move to next {
    return None


def extract_json(text: str) -> Optional[dict]:
    if not text:
        return None
    text = text.strip()
    # strip markdown code fences
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
        text = text.strip()
    # direct parse first (fast path)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    # balanced-brace scan (handles LLM narrative around JSON)
    return _extract_json_object(text)


class LLMClient:
    def __init__(self, base_url: str, api_key: str, model: str, max_retries: int = 2):
        self.model = model
        self.max_retries = max_retries
        self.base_url = base_url
        self.client = OpenAI(base_url=base_url, api_key=api_key)

    def send(
        self,
        system_prompt: str,
        user_prompt: str,
        max_tokens: int = 16384,
    ) -> str:
        last_error = None
        for attempt in range(self.max_retries + 1):
            try:
                resp = self.client.chat.completions.create(
                    model=self.model,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                    max_tokens=max_tokens,
                    timeout=60,
                )
                content = resp.choices[0].message.content or ""
                logger.info("LLM %s OK (%d tokens)", self.model,
                            resp.usage.total_tokens if resp.usage else 0)
                return content
            except RateLimitError as e:
                last_error = e
                wait = min(2 ** attempt * 5, 30)
                logger.warning("Rate limited, retrying in %ds (attempt %d/%d)", wait, attempt + 1, self.max_retries)
                time.sleep(wait)
            except APITimeoutError as e:
                last_error = e
                logger.warning("Timeout (attempt %d/%d)", attempt + 1, self.max_retries)
                if attempt < self.max_retries:
                    time.sleep(2)
            except APIError as e:
                last_error = e
                logger.error("API error: %s", e)
                if attempt < self.max_retries:
                    time.sleep(2)
            except Exception as e:
                logger.error("Unexpected LLM error: %s", e)
                raise
        logger.error("LLM failed after %d retries: %s", self.max_retries, last_error)
        return ""

    def send_json(
        self,
        system_prompt: str,
        user_prompt: str,
        max_tokens: int = 16384,
    ) -> Optional[dict]:
        content = self.send(system_prompt, user_prompt, max_tokens)
        result = extract_json(content)
        if result is None:
            logger.warning("Failed to parse LLM JSON response (len=%d)", len(content))
        return result
