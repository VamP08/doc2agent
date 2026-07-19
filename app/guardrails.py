"""Human-in-the-loop guardrails: write operations require explicit approval.

Read-only calls (GET/HEAD) execute freely. Anything that mutates state
(POST/PUT/PATCH/DELETE) pauses the agent until a human approves or denies it
in the UI — unless the user has explicitly enabled auto-approve.
"""
import threading
import uuid

from .models import Endpoint

WRITE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
APPROVAL_TIMEOUT_S = 180.0


def requires_approval(endpoint: Endpoint) -> bool:
    return endpoint.method.upper() in WRITE_METHODS


class ApprovalRegistry:
    """Pending approval requests, resolved from another request thread."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._pending: dict[str, dict] = {}

    def create(self, info: dict) -> str:
        approval_id = uuid.uuid4().hex[:12]
        with self._lock:
            self._pending[approval_id] = {
                "event": threading.Event(),
                "approved": False,
                "info": info,
            }
        return approval_id

    def wait(self, approval_id: str, timeout: float = APPROVAL_TIMEOUT_S) -> bool:
        """Block the agent thread until resolved; timeout means denied."""
        with self._lock:
            entry = self._pending.get(approval_id)
        if entry is None:
            return False
        entry["event"].wait(timeout)
        with self._lock:
            self._pending.pop(approval_id, None)
        return entry["approved"]

    def resolve(self, approval_id: str, approved: bool) -> bool:
        with self._lock:
            entry = self._pending.get(approval_id)
            if entry is None:
                return False
            entry["approved"] = approved
            entry["event"].set()
            return True


APPROVALS = ApprovalRegistry()
