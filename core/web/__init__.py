"""Web workbench adapter package."""

__all__ = ["app", "create_app"]


def __getattr__(name: str):
    if name == "app":
        from .app import app as fastapi_app

        return fastapi_app
    if name == "create_app":
        from .app import create_app as create_fastapi_app

        return create_fastapi_app
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
