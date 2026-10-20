"""Server-side read-only policy enforcement.

Enforces that only explicitly approved read-only operations may execute.
This is an independent policy layer that operates in addition to
catalog enablement and approval status checks.

Not every GET is automatically safe - legacy endpoints may have side effects.
The policy requires explicit approval in the catalog.
"""

from __future__ import annotations

from schemas.catalog import CatalogEntry
from schemas.errors import ErrorCode, McpToolError

# HTTP methods considered potentially read-only.
# Even GET operations require explicit catalog approval.
_READ_ONLY_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


def enforce_read_only_policy(entry: CatalogEntry) -> None:
    """Enforce the server-side read-only execution policy.

    Checks:
    1. The HTTP method must be in the allowed read-only set.
    2. The catalog entry's access_mode must be 'read_only'.
    3. The entry must be explicitly enabled.
    4. The entry must be explicitly approved.

    Args:
        entry: The catalog entry to check.

    Raises:
        McpToolError: If the operation violates read-only policy.
    """
    method = entry.method.upper()

    # Check HTTP method
    if method not in _READ_ONLY_METHODS:
        raise McpToolError.from_code(
            ErrorCode.READ_ONLY_VIOLATION,
            f"HTTP method '{method}' is not permitted under the read-only policy. "
            f"Only {sorted(_READ_ONLY_METHODS)} methods are allowed.",
            details={
                "endpoint_name": entry.endpoint_name,
                "method": method,
                "policy": "read_only",
            },
        )

    # Check access_mode
    if entry.access_mode != "read_only":
        raise McpToolError.from_code(
            ErrorCode.READ_ONLY_VIOLATION,
            f"Operation '{entry.endpoint_name}' ({method}) has access_mode "
            f"'{entry.access_mode}', which is not permitted under the read-only policy.",
            details={
                "endpoint_name": entry.endpoint_name,
                "method": method,
                "access_mode": entry.access_mode,
            },
        )

    # Check enabled status
    if not entry.enabled:
        raise McpToolError.from_code(
            ErrorCode.DISABLED_ENDPOINT,
            f"Operation '{entry.endpoint_name}' ({method}) is disabled "
            f"and cannot be executed.",
            details={
                "endpoint_name": entry.endpoint_name,
                "method": method,
            },
        )

    # Check approval status
    if entry.approval_status != "approved":
        raise McpToolError.from_code(
            ErrorCode.UNAPPROVED_ENDPOINT,
            f"Operation '{entry.endpoint_name}' ({method}) has approval status "
            f"'{entry.approval_status}' and cannot be executed. "
            f"Only 'approved' operations may run.",
            details={
                "endpoint_name": entry.endpoint_name,
                "method": method,
                "approval_status": entry.approval_status,
            },
        )
