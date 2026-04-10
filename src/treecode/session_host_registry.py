"""Weak reference to the active shared SessionHost (TUI/backend process)."""

from __future__ import annotations

import weakref
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from treecode.ui.session_host import SessionHost

_ref: weakref.ref | None = None


def set_active_session_host(host: SessionHost | None) -> None:
    """Register the current process session host (or clear)."""
    global _ref
    if host is None:
        _ref = None
        return
    _ref = weakref.ref(host)


def get_active_session_host() -> SessionHost | None:
    """Return the active SessionHost if still alive."""
    if _ref is None:
        return None
    return _ref()


__all__ = ["set_active_session_host", "get_active_session_host"]
