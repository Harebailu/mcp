"""Inbound MCP JWT expiration-claim-only validation.

IMPORTANT SECURITY LIMITATION:
This module checks ONLY whether the JWT's 'exp' claim indicates the token
has expired. It does NOT:
- Verify the JWT signature
- Validate the issuer (iss)
- Validate the audience (aud)
- Check not-before (nbf)
- Evaluate roles or permissions
- Perform tenant checks

Checking an 'exp' claim without signature verification is only an
expiration-claim check. It does not authenticate the token's issuer
or prove the token is genuine.

The .NET API layer remains responsible for enforcing its own
authentication and authorization requirements downstream.
"""

from __future__ import annotations

import time
from typing import Any, Optional

import jwt  # PyJWT

from schemas.errors import ErrorCode, McpToolError


def validate_token_expiry(
    token: Optional[str],
    expiration_claim: str = "exp",
    clock_skew_seconds: int = 0,
) -> dict[str, Any]:
    """Validate only the expiration claim of an inbound JWT.

    Args:
        token: The raw bearer token string (without 'Bearer ' prefix).
        expiration_claim: The claim name for expiration (default: 'exp').
        clock_skew_seconds: Allowed clock skew in seconds (default: 0).

    Returns:
        The decoded JWT payload (unverified - for expiration check only).

    Raises:
        McpToolError: With appropriate error code for missing, malformed,
                      unparseable, or expired tokens.
    """
    if not token or not token.strip():
        raise McpToolError.from_code(
            ErrorCode.TOKEN_MISSING,
            "Authentication token is missing. A bearer token is required.",
        )

    token = token.strip()

    # Remove 'Bearer ' prefix if present
    if token.lower().startswith("bearer "):
        token = token[7:].strip()

    if not token:
        raise McpToolError.from_code(
            ErrorCode.TOKEN_MISSING,
            "Authentication token is empty after removing the Bearer prefix.",
        )

    # Decode without signature verification (expiration check only)
    try:
        payload = jwt.decode(
            token,
            options={
                "verify_signature": False,
                "verify_exp": False,
                "verify_aud": False,
                "verify_iss": False,
                "verify_nbf": False,
            },
            algorithms=["HS256", "HS384", "HS512", "RS256", "RS384", "RS512", "ES256", "ES384", "ES512"],
        )
    except jwt.exceptions.DecodeError as e:
        raise McpToolError.from_code(
            ErrorCode.TOKEN_MALFORMED,
            "The authentication token is malformed and cannot be decoded.",
        ) from e
    except Exception as e:
        raise McpToolError.from_code(
            ErrorCode.TOKEN_UNPARSEABLE,
            "The authentication token could not be parsed.",
        ) from e

    # Check for the expiration claim
    if expiration_claim not in payload:
        raise McpToolError.from_code(
            ErrorCode.TOKEN_UNPARSEABLE,
            f"The token does not contain the '{expiration_claim}' claim. "
            f"Expiration cannot be established.",
            details={"available_claims": list(payload.keys())},
        )

    exp_value = payload[expiration_claim]

    # Validate exp is a number
    if not isinstance(exp_value, (int, float)):
        raise McpToolError.from_code(
            ErrorCode.TOKEN_UNPARSEABLE,
            f"The '{expiration_claim}' claim is not a valid numeric timestamp.",
        )

    # Check expiration (UTC comparison)
    current_time = time.time()
    if current_time > (exp_value + clock_skew_seconds):
        raise McpToolError.from_code(
            ErrorCode.TOKEN_EXPIRED,
            "The authentication token has expired.",
            details={
                "expired_at_utc": exp_value,
                "current_utc": int(current_time),
                "clock_skew_seconds": clock_skew_seconds,
            },
        )

    return payload


def extract_bearer_token(authorization_header: Optional[str]) -> Optional[str]:
    """Extract the token from an Authorization header value.

    Args:
        authorization_header: The full Authorization header value.

    Returns:
        The token string, or None if the header is absent/empty.
    """
    if not authorization_header or not authorization_header.strip():
        return None

    header = authorization_header.strip()
    if header.lower().startswith("bearer "):
        return header[7:].strip() or None

    # Return as-is if no Bearer prefix (let validation handle format)
    return header
