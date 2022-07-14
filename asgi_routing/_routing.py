import re
from typing import Awaitable, Dict, Iterable, Tuple
from urllib.parse import quote

from routrie import Router as RoutrieRouter
from asgi_routing._types import Scope, ASGIApp, Receive, Send


class Route:
    def __init__(self, path: str, app: ASGIApp) -> None:
        self.path = self.match_path = path
        self.app = app

    def __call__(self, scope: Scope, receive: Receive, send: Send) -> Awaitable[None]:
        scope["path"] = scope["path"].removeprefix(self.match_path.format(**scope["path_params"]))
        return self.app(scope, receive, send)


class Mount(Route):
    def __init__(self, path: str, app: ASGIApp) -> None:
        self.path = path
        self.match_path = self.path + "/{path:path}"
        self.app = app

    def __call__(self, scope: Scope, receive: Receive, send: Send) -> Awaitable[None]:
        scope["path"] = scope["path"].removeprefix(self.path)
        scope["path_params"].pop("path")
        return self.app(scope, receive, send)


async def not_found_app(scope: Scope, receive: Receive, send: Send) -> None:
    await send(
        {
            "type": "http.response.start",
            "status": 404,
            "headers": [(b"Content-Type", b"text/plain")],
        }
    )
    await send(
        {
            "type": "http.response.body",
            "body": b"Not Found",
            "more_body": False,
        }
    )


def build_redirect_app(new_url: str) -> ASGIApp:
    async def app(scope: Scope, receive: Receive, send: Send) -> None:
        await send(
            {
                "type": "http.response.start",
                "status": 307,
                "headers": [(b"Location", new_url.encode())],
            }
        )
        await send({"type": "http.response.body", "body": b"", "more_body": False})
    return app


def build_redirect_url(scope: Scope, new_path: str) -> str:
    scheme = scope.get("scheme", "http")
    server = scope.get("server", None)
    path = scope.get("root_path", "") + new_path
    query_string = scope.get("query_string", b"")

    host_header = None
    headers: "Iterable[Tuple[bytes, bytes]]" = scope["headers"]
    for key, value in headers:
        if key == b"host":
            host_header = value.decode("latin-1")
            break

    if host_header is not None:
        url = f"{scheme}://{host_header}{path}"
    elif server is None:
        url = path
    else:
        host, port = server
        default_port = {"http": 80, "https": 443, "ws": 80, "wss": 443}[scheme]
        if port == default_port:
            url = f"{scheme}://{host}{path}"
        else:
            url = f"{scheme}://{host}:{port}{path}"

    if query_string:
        url += "?" + query_string.decode()
    return url



def convert_path_to_routrie_path(path: str) -> str:
    param_patt = r"([a-zA-Z_][a-zA-Z0-9_]*)"
    path_item_patt = rf"\/{{{param_patt}}}"
    wildcard_patt = rf"\/{{{param_patt}:path}}$"
    path = re.sub(wildcard_patt, lambda match: f"/*{match.group(1)}", path)
    path = re.sub(path_item_patt, lambda match: f"/:{match.group(1)}", path)
    return path


class Router:
    """Simple HTTP Router.

    This router maps paths like:
    - "/{param1}/bar/{param2}
    - "/bar/{catchall:path}

    To ASGI applications.
    """
    def __init__(
        self,
        routes: Iterable[Route],
        *,
        not_found_handler: ASGIApp = not_found_app,
        redirect_slashes: bool = True,
    ) -> None:
        self.redirect_slashes = redirect_slashes
        self._router = RoutrieRouter(
            {convert_path_to_routrie_path(r.match_path): r for r in routes}
        )
        self._not_found_handler = not_found_handler

    def __call__(self, scope: Scope, receive: Receive, send: Send) -> Awaitable[None]:
        if scope["type"] not in ("http", "websocket"):
            raise ValueError("Router can only handle http or websocket scopes")
        path: str = scope["path"]
        match = self._router.find(path)
        if match is None:
            if scope["type"] == "http" and self.redirect_slashes and path != "/":
                if path.endswith("/"):
                    new_path = path.rstrip("/")
                else:
                    new_path = path + "/"
                if self._router.find(new_path):
                    new_url = quote(str(build_redirect_url(scope, new_path)), safe=":/%#?=@[]!$&'()*+,;")
                    return build_redirect_app(new_url)(scope, receive, send)
            return self._not_found_handler(scope, receive, send)
        else:
            app, params = match
            path_params: "Dict[str, str]"
            if "path_params" in scope:
                path_params = scope["path_params"]
            else:
                path_params = {}
            path_params.update(params)
            scope["path_params"] = path_params
            return app(scope, receive, send)
