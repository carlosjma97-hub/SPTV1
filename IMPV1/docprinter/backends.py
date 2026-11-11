from __future__ import annotations

from .backend_base import Backend


def get_backend(fake: bool = False) -> Backend:
    if fake:
        from .backend_fake import FakeBackend
        return FakeBackend.demo()
    from .backend_windows import WindowsBackend
    return WindowsBackend()
