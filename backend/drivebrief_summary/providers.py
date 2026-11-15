import json
import os
import socket
from dataclasses import dataclass
from typing import Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, build_opener, HTTPRedirectHandler

from .errors import SummaryError
from .models import Article, Draft
from .segments import split_article
from .prompt import SYSTEM_PROMPT


@dataclass(frozen=True)
class Settings:
    model: str = "openai/gpt-oss-20b"
    base_url: str = "https://api.groq.com/openai/v1"
    json_mode: str = "schema"
    timeout: float = 30
    max_tokens: int = 8192
    temperature: float = 0.2
    reasoning_effort: str = "low"
    summary_length: str = "default"

    def __post_init__(self):
        if self.summary_length not in ("default", "short", "medium", "long"):
            raise SummaryError("config", "Invalid summary length")
        endpoint = urlsplit(self.base_url)
        if endpoint.scheme != "https" or not endpoint.netloc or endpoint.username or endpoint.password or endpoint.query or endpoint.fragment:
            raise SummaryError("config", "LLM_BASE_URL must be an HTTPS base URL without credentials/query/fragment")
        if self.reasoning_effort not in ("low", "medium", "high", "omit"):
            raise SummaryError("config", "Invalid reasoning effort")
        if not self.model.strip() or self.json_mode not in ("schema", "object"):
            raise SummaryError("config", "Invalid model or JSON mode")
        if not 1 <= self.timeout <= 120 or not 256 <= self.max_tokens <= 8192:
            raise SummaryError("config", "Invalid timeout/token limit")

    @classmethod
    def from_env(cls):
        try:
            return cls(model=os.getenv("LLM_MODEL", cls.model),
                       base_url=os.getenv("LLM_BASE_URL", cls.base_url).rstrip("/"),
                       json_mode=os.getenv("LLM_JSON_MODE", "schema"),
                       timeout=float(os.getenv("LLM_TIMEOUT_SECONDS", "30")),
                       max_tokens=int(os.getenv("LLM_MAX_TOKENS", str(cls.max_tokens))),
                       reasoning_effort=os.getenv("LLM_REASONING_EFFORT", "low"),
                       summary_length=os.getenv("LLM_SUMMARY_LENGTH", "default"))
        except ValueError:
            raise SummaryError("config", "Numeric LLM configuration is invalid") from None


class Provider(Protocol):
    name: str
    settings: Settings
    def generate(self, article: Article) -> str: ...


class NoRedirect(HTTPRedirectHandler):
    # Never forward an Authorization header to a redirect destination.
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def http_diagnostic(exc: HTTPError) -> str:
    """Never expose arbitrary error messages, header values, request ids or echoed content."""
    headers = exc.headers or {}
    content_type = headers.get("Content-Type", "").split(";")[0].strip().lower()
    kind = "json" if content_type == "application/json" else "html" if content_type == "text/html" else "other"
    edge = headers.get("Server", "").strip().lower() == "cloudflare"
    code = "unrecognized"
    error_type = "unrecognized"
    known_codes = {
        "model_permission_blocked", "model_not_found", "permission_denied", "access_denied",
        "insufficient_permissions", "json_validate_failed", "invalid_json_schema",
        "invalid_api_key", "rate_limit_exceeded", "organization_restricted",
    }
    known_types = {"permission_error", "authentication_error", "invalid_request_error",
                   "rate_limit_error", "server_error"}
    try:
        raw = exc.read(16_384) if exc.fp is not None else b""
        error = json.loads(raw).get("error", {})
        if isinstance(error, dict):
            candidate = error.get("code")
            if isinstance(candidate, str) and candidate in known_codes:
                code = candidate
            candidate = error.get("type")
            if isinstance(candidate, str) and candidate in known_types:
                error_type = candidate
    except (ValueError, AttributeError, KeyError, TypeError, OSError):
        pass
    finally:
        if exc.fp is not None:
            try:
                exc.close()
            except (OSError, AttributeError, KeyError):
                pass
    # Presence flags, not raw identifiers: an upstream may echo secrets in any field.
    return (
        f"status={exc.code}; body={kind}; cloudflare={edge}; "
        f"request_id_present={bool(headers.get('x-request-id') or headers.get('x-groq-request-id'))}; "
        f"cf_ray_present={bool(headers.get('cf-ray'))}; "
        f"error_code={code}; error_type={error_type}"
    )


class GroqProvider:
    name = "groq"

    def __init__(self, settings: Settings):
        self.settings = settings

    def generate(self, article: Article) -> str:
        key = os.getenv("GROQ_API_KEY", "").strip()
        if not key:
            raise SummaryError("missing_api_key", "GROQ_API_KEY is not set; use --provider mock for offline tests")
        settings = self.settings
        response_format = {"type": "json_object"}
        if settings.json_mode == "schema":
            response_format = {"type": "json_schema", "json_schema": {
                "name": "news_summary", "strict": True, "schema": Draft.model_json_schema()}}
        article_input = {"article_title": article.title,
                         "source_spans": [span.as_dict() for span in split_article(article)]}
        if settings.summary_length != "default":
            article_input["summary_length"] = settings.summary_length
        payload = {
            "model": settings.model, "temperature": settings.temperature,
            "max_completion_tokens": settings.max_tokens,
            "response_format": response_format,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": json.dumps(
                    article_input, ensure_ascii=False)},
            ],
        }
        # Other models may not accept reasoning_effort. Do not send GPT-OSS-specific options blindly.
        if settings.model in ("openai/gpt-oss-20b", "openai/gpt-oss-120b") and settings.reasoning_effort != "omit":
            payload["reasoning_effort"] = settings.reasoning_effort
        request = Request(settings.base_url + "/chat/completions",
                          data=json.dumps(payload).encode("utf-8"),
                          headers={"Authorization": "Bearer " + key, "Content-Type": "application/json",
                                   "Accept": "application/json", "User-Agent": "DriveBriefSummary/0.1"})
        try:
            with build_opener(NoRedirect()).open(request, timeout=settings.timeout) as response:
                raw = response.read(1_000_001)
            if len(raw) > 1_000_000:
                raise SummaryError("provider_response", "Provider response exceeds size limit")
            envelope = json.loads(raw)
            choice = envelope["choices"][0]
            if choice.get("finish_reason") == "length":
                raise SummaryError("provider_token_limit",
                                   f"LLM reached max_completion_tokens={settings.max_tokens}; "
                                   "this budget includes reasoning and final JSON; no automatic retry")
            if choice.get("finish_reason") != "stop" or choice["message"].get("refusal"):
                raise SummaryError("provider_incomplete", "Provider refused or did not finish the JSON output")
            content = choice["message"]["content"]
            if not isinstance(content, str) or not content.strip():
                raise TypeError()
            return content
        except HTTPError as exc:
            diagnostic = http_diagnostic(exc)
            raise SummaryError("provider_http", "LLM HTTP " + diagnostic +
                               f"; mode={settings.json_mode}; max_completion_tokens={settings.max_tokens}; "
                               "no automatic retry or response-format fallback") from None
        except (URLError, TimeoutError, socket.timeout, OSError):
            raise SummaryError("provider_network", "LLM connection failed or timed out; no automatic retry") from None
        except (ValueError, KeyError, IndexError, TypeError, AttributeError):
            raise SummaryError("provider_response", "Unexpected LLM response envelope") from None


class MockProvider:
    """Deterministic extractive transport substitute; NOT AI summarization."""
    name = "mock-source-ids-v1"

    def __init__(self, summary_length="default"):
        self.settings = Settings(model="mock-source-ids-v1", summary_length=summary_length)
        self.calls = 0

    def generate(self, article: Article) -> str:
        self.calls += 1
        # A deterministic paraphrase exercises the same ID resolver as a real draft.
        spans = [span for span in split_article(article) if span.field == "body"][:8]
        texts = [span.text.replace("발표했습니다", "알렸습니다") for span in spans]
        count = {"default": 3, "short": 1, "medium": 2, "long": 3}[self.settings.summary_length]
        links = [{"target": "tts_sentences", "index": i, "evidence_ids": [span.id]}
                 for i, span in enumerate(spans[:count])]
        links.extend([
            {"target": "one_line", "index": 0, "evidence_ids": [spans[0].id]},
            {"target": "detail", "index": 0, "evidence_ids": [span.id for span in spans]},
        ])
        result = Draft(status="ok", reason="", tts_sentences=texts[:count],
                       one_line=texts[0], detail="\n".join(texts), evidence_links=links)
        return result.model_dump_json()
