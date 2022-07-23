import re
from functools import lru_cache
from typing import Awaitable, Dict, Iterable, Tuple
from urllib.parse import quote

from routrie import Router as RoutrieRouter

from asgi_routing._lifespan_dispatcher import LifespanDispatcher
from asgi_routing._types import ASGIApp, Receive, Scope, Send


class Route:
    """A generic Route that maps an exact path match to an ASGI app.

    A Route must have:
    1. A `match_path` attribute that is used by the Router
    2. A `__call__` method that is an ASGI app
    """

    __slots__ = ("path", "match_path", "app")

    def __init__(self, path: str, app: ASGIApp) -> None:
        self.path = self.match_path = path
        self.app = app

    def __call__(self, scope: Scope, receive: Receive, send: Send) -> Awaitable[None]:
        if scope["type"] != "http":
            return self.app(scope, receive, send)
        prefix = self.match_path.format(**scope["path_params"])
        scope["path"] = scope["path"][len(prefix) :]
        return self.app(scope, receive, send)


async def not_found_app(scope: Scope, receive: Receive, send: Send) -> None:
    """ASGI app that returns a text/plain 404 response"""
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


@lru_cache(maxsize=1024)
def build_redirect_app(new_url: str) -> ASGIApp:
    """Factory to create an ASGI app that redirects to `new_url`"""

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
    """Build the URL to redirect to from the Scope.

    This functions parses the Scope to extract the scheme, query string
    and so on and builds a full URL that we can redirect to.
    """
    scheme = scope.get("scheme", "http")
    server = scope.get("server", None)
    path = scope.get("root_path", "") + new_path
    query_string = scope.get("query_string", b"")

    host_header = None
    headers: "Iterable[Tuple[bytes, bytes]]" = scope["headers"]
    for key, value in headers:
        if key.decode("latin-1").lower() == "host":
            host_header = value.decode("latin-1").lower()
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
    """Convert path templates using braces (`/users/{username}`)
    to colons (`/users/:username`).

    Starlette uses braces and braces are nice in Python because they
    get syntax-highlighted.
    To keep _some_ backwards compatibility with Starlette and to
    benefit from syntax highlighting we use braces, but routrie/path-tree
    use colons for path parameters and asterisks for wildcard parameters,
    so we need to do some conversion at initialization time.
    """
    # TODO: we should check if the template already has some colons or *.
    # Braces are actually not allowed characters so those are always okay.
    # But : and * are allowed in URLs so if they exist we should at least error,
    # but perhaps we could come up with some escaping mechanism

    param_patt = r"([a-zA-Z_][a-zA-Z0-9_]*)"
    path_item_patt = rf"{{{param_patt}}}(?:(\/)|$)"
    wildcard_patt = rf"{{{param_patt}:path}}$"

    def wildcard_patt_repl(match: "re.Match[str]") -> str:
        return f"*{match.group(1)}"

    path = re.sub(wildcard_patt, wildcard_patt_repl, path)

    def path_patt_repl(match: "re.Match[str]") -> str:
        return f":{match.group(1)}{'/' if match.group(2) else ''}"

    path = re.sub(path_item_patt, path_patt_repl, path)
    return path


class Router:
    """Simple HTTP Router that maps paths to Routes.

    Paths can contain parameter templates as well as wildcards:
    - "/{param1}/bar/{param2} -> /1/bar/2 (param1 = "1", param2 = "2")
    - "/bar/{catchall:path} -> /bar/foo/baz (catchall = "foo/baz")

    For more details on matching, see the [path-tree] docs,
    but note that we use braces instead of `":"` and `"*"`.

    [path-tree]: https://github.com/viz-rs/path-tree
    """

    __slots__ = ("redirect_slashes", "_router", "_not_found_handler", "_apps")

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
        self._apps = [r for r in routes]
        self._not_found_handler = not_found_handler

    def __call__(self, scope: Scope, receive: Receive, send: Send) -> Awaitable[None]:
        if scope["type"] == "lifespan":
            return LifespanDispatcher(self._apps)(scope, receive, send)
        if scope["type"] not in ("http", "websocket"):  # pragma: no cover
            raise ValueError("Routing can only handle http or websocket scopes")
        path: "str" = scope["path"]
        match = self._router.find(path)
        if match is None:
            if scope["type"] == "http" and self.redirect_slashes and path != "/":
                if path.endswith("/"):
                    new_path = path.rstrip("/")
                else:
                    new_path = path + "/"
                if self._router.find(new_path):
                    new_url = quote(
                        build_redirect_url(scope, new_path),
                        safe=":/%#?=@[]!$&'()*+,;",
                    )
                    return build_redirect_app(new_url)(scope, receive, send)
            return self._not_found_handler(scope, receive, send)
        else:
            app, params = match
            if "path_params" in scope:
                path_params: "Dict[str, str]" = scope["path_params"]
                path_params.update(params)
            else:
                path_params = dict(params)
            scope["path_params"] = path_params
            return app(scope, receive, send)
