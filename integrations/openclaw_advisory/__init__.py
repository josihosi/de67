"""Task-bound, advisory-only OpenClaw consultation transport."""

from .advisory_consult import (
    AdvisoryAdapter,
    AdvisoryError,
    AuthorizationError,
    ConsultationReply,
)

__all__ = [
    "AdvisoryAdapter",
    "AdvisoryError",
    "AuthorizationError",
    "ConsultationReply",
]
