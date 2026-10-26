"""AI providers.

Every supported free option speaks the same "OpenAI-compatible chat completions" format, so ONE class does the HTTP
work and each provider is just a preset (URL, default model, which key to use):

    gemini  - Google Gemini API free tier (key from Google AI Studio, no payment method)    <- recommended
    groq    - Groq free plan (key from console.groq.com)
    ollama  - a model running on your own PC with Ollama (free, no key, needs RAM / disk)
    none    - AI switched off: generation returns AI_NOT_CONFIGURED; review + bank keep working

To add another provider later, add a preset below (or write a new AIProvider subclass) - nothing else changes.
There is deliberately NO automatic fallback to another (possibly paid) provider when a free quota runs out.
"""
import base64
import logging
from dataclasses import dataclass

import requests

from app.ai import errors

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Preset:
    base_url: str
    default_model: str
    key_setting: str | None      # name of the Config/.env setting that holds the API key (None = no key needed)
    json_mode: bool              # send response_format={"type":"json_object"}
    vision: bool = False         # can read pictures (used for PDFs made of photos / scans)


PRESETS = {
    "gemini": Preset("https://generativelanguage.googleapis.com/v1beta/openai", "gemini-3.5-flash-lite", "GEMINI_API_KEY",
                     json_mode=False, vision=True),   # Gemini follows the JSON instructions in the prompt; we validate everything anyway
    "groq": Preset("https://api.groq.com/openai/v1", "openai/gpt-oss-20b", "GROQ_API_KEY", json_mode=True),
    "ollama": Preset("http://localhost:11434/v1", "qwen2.5:7b", None, json_mode=True),
}


class AIProvider:
    """Interface used by the rest of the app."""
    name = "base"
    model = ""
    supports_images = False

    def complete(self, system: str, user: str, images: list[bytes] | None = None) -> str:
        """Send one prompt (plus optional JPEG pictures) and return the model's raw text answer.
        Raises errors.AIError on any failure."""
        raise NotImplementedError


class OpenAICompatibleProvider(AIProvider):
    def __init__(self, name: str, base_url: str, model: str, api_key: str | None, *, json_mode: bool,
                 timeout: int, max_output_tokens: int | None = None, vision: bool = False):
        self.name, self.base_url, self.model = name, base_url.rstrip("/"), model
        self.supports_images = vision
        self._api_key, self.json_mode, self.timeout = api_key, json_mode, timeout
        self.max_output_tokens = max_output_tokens

    def complete(self, system: str, user: str, images: list[bytes] | None = None) -> str:
        content = user
        if images:
            if not self.supports_images:
                raise errors.AIError("AI_NO_VISION", f"The AI provider '{self.name}' cannot read pictures.", status=422)
            content = [{"type": "text", "text": user}] + [
                {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64," + base64.b64encode(img).decode()}}
                for img in images]
        body = {
            "model": self.model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": content}],
            "temperature": 0.2 if images else 0.4,
        }
        if self.json_mode and not images:
            body["response_format"] = {"type": "json_object"}
        if self.max_output_tokens:
            body["max_tokens"] = self.max_output_tokens
        headers = {"Content-Type": "application/json"}
        if self._api_key:
            headers["Authorization"] = "Bearer " + self._api_key

        try:
            resp = requests.post(self.base_url + "/chat/completions", json=body, headers=headers, timeout=self.timeout)
        except requests.Timeout:
            raise errors.timeout()
        except requests.RequestException:
            log.warning("AI provider %s could not be reached", self.name)   # no URL/key in the log line
            raise errors.unavailable()

        if resp.status_code in (401, 403):
            raise errors.auth_failed()
        if resp.status_code == 429:
            raise errors.rate_limited(_retry_after(resp))
        if resp.status_code == 408 or resp.status_code >= 500:
            raise errors.unavailable()
        if resp.status_code >= 400:
            log.warning("AI provider %s refused the request: HTTP %s", self.name, resp.status_code)
            raise errors.request_rejected()

        try:
            data = resp.json()
            choice = data["choices"][0]
            content = choice["message"]["content"]
        except (ValueError, KeyError, IndexError, TypeError):
            raise errors.bad_response("unexpected reply format")
        if isinstance(content, list):          # some providers return a list of text parts
            content = "".join(p.get("text", "") for p in content if isinstance(p, dict))
        if not isinstance(content, str) or not content.strip():
            log.warning("AI provider %s returned an empty answer (finish_reason=%s)", self.name, choice.get("finish_reason"))
            raise errors.bad_response("empty answer")
        if choice.get("finish_reason") == "length":
            # Answer was cut off at the length limit: hand it on anyway - complete questions in it are still kept.
            log.info("AI answer from %s was cut off at the length limit; keeping the complete part", self.name)
        return content


def _retry_after(resp) -> float | None:
    try:
        return float(resp.headers.get("Retry-After"))
    except (TypeError, ValueError):
        return None


def _resolve(config) -> tuple[str, Preset | None, str | None]:
    """Returns (provider name, preset, problem text or None)."""
    name = (config.get("AI_PROVIDER") or "none").lower()
    if name in ("", "none", "off", "disabled"):
        return "none", None, "Set AI_PROVIDER (gemini, groq or ollama) in backend/.env."
    preset = PRESETS.get(name)
    if preset is None:
        return name, None, f"Unknown AI_PROVIDER '{name}'. Use one of: {', '.join(PRESETS)}."
    if preset.key_setting and not config.get(preset.key_setting):
        return name, preset, f"Add {preset.key_setting} to backend/.env."
    return name, preset, None


def provider_status(config) -> dict:
    """Safe summary for the UI (never includes the key)."""
    name, preset, problem = _resolve(config)
    return {
        "provider": name,
        "model": (config.get("AI_MODEL") or (preset.default_model if preset else None)),
        "configured": problem is None,
        "message": problem,
        "reads_images": bool(problem is None and preset and preset.vision),
    }


def get_provider(config) -> AIProvider:
    """Build the provider chosen in .env. Raises AI_NOT_CONFIGURED when it is missing or incomplete."""
    name, preset, problem = _resolve(config)
    if problem:
        raise errors.not_configured(problem)
    key = config.get(preset.key_setting) if preset.key_setting else None
    max_tokens = config.get("AI_MAX_OUTPUT_TOKENS")
    return OpenAICompatibleProvider(
        name,
        config.get("AI_BASE_URL") or preset.base_url,
        config.get("AI_MODEL") or preset.default_model,
        key,
        json_mode=preset.json_mode,
        timeout=int(config.get("AI_TIMEOUT_SECONDS", 90)),
        max_output_tokens=int(max_tokens) if max_tokens else None,
        vision=preset.vision,
    )
