"""Request context for the current validated MCP request.

Carries validated context information through the request lifecycle
without exposing the raw token.
"""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field


class RequestContext(BaseModel):
    """Represents the current validated request context.

    This model carries request-level metadata through the processing
    pipeline. It does NOT carry the raw token.
    """
    token_claims: Optional[dict[str, Any]] = None
    token_expiry_checked: bool = False
    auth_enabled: bool = True

    @property
    def is_authenticated_context(self) -> bool:
        """Whether this context passed the expiration check.

        NOTE: This only means the expiration claim was checked.
        It does NOT mean the token's signature was verified or
        that the token is genuinely authenticated.
        """
        return self.token_expiry_checked
