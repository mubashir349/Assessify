"""Errors from the AI layer. Messages are safe to show to users: they never contain keys or raw provider output."""


class AIError(Exception):
    def __init__(self, code: str, message: str, *, status: int = 503, retryable: bool = False,
                 retry_after: float | None = None):
        super().__init__(message)
        self.code, self.message, self.status = code, message, status
        self.retryable, self.retry_after = retryable, retry_after


def not_configured(detail: str) -> AIError:
    return AIError("AI_NOT_CONFIGURED", "AI question generation is not set up on this server. " + detail, status=503)


def auth_failed() -> AIError:
    return AIError("AI_AUTH_FAILED", "The AI service rejected the API key. Ask the administrator to check the key in .env.",
                   status=503)


def rate_limited(retry_after: float | None) -> AIError:
    return AIError("AI_RATE_LIMITED", "The free AI quota or rate limit was reached. Wait a minute and try again "
                   "(daily free quotas reset once a day).", status=429, retryable=True, retry_after=retry_after)


def timeout() -> AIError:
    return AIError("AI_TIMEOUT", "The AI service took too long to answer. Try again, or ask for fewer questions.",
                   status=504, retryable=True)


def unavailable() -> AIError:
    return AIError("AI_UNAVAILABLE", "The AI service is unavailable right now. Please try again later.",
                   status=503, retryable=True)


def request_rejected() -> AIError:
    return AIError("AI_REQUEST_REJECTED", "The AI service refused the request. Check the AI_MODEL setting in .env.",
                   status=502)


def bad_response(why: str = "") -> AIError:
    return AIError("AI_BAD_RESPONSE", "The AI service returned an answer that could not be used" + (f" ({why})" if why else "")
                   + ". Please try again.", status=502, retryable=True)
