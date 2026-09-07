"""Compatibility entrypoint for the walk-record experiment; HTTP is owned by tools."""

from tools.walk_trace.record_server import create_app, main

__all__ = ["create_app", "main"]

if __name__ == "__main__":
    main()
