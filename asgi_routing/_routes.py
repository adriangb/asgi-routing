from typing import Awaitable

from asgi_routing._router import Route
from asgi_routing._types import ASGIApp, Receive, Scope, Send


class Mount(Route):
    """A route that matches a path prefix to an ASGI app."""

    def __init__(self, path_prefix: str, app: ASGIApp) -> None:
        super().__init__(path_prefix, app)
        self.match_path = path_prefix + "{path:path}"

    def __call__(self, scope: Scope, receive: Receive, send: Send) -> Awaitable[None]:
        if scope["type"] != "http":
            return self.app(scope, receive, send)
        scope["path"] = scope["path"][len(self.path) :]
        # the default catches the case where "path" would be empty
        # but routrie/path-tree returns nothing in these cases
        scope["path_params"].pop("path", None)
        return self.app(scope, receive, send)
