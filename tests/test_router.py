from contextlib import asynccontextmanager
from typing import Any, AsyncIterator, List, Set

import pytest
from starlette.applications import Starlette
from starlette.datastructures import Headers
from starlette.responses import Response
from starlette.testclient import TestClient
from starlette.types import Message, Receive, Scope, Send

from asgi_routing import Mount, Route, Router


def get_client(router: Router) -> TestClient:
    # Wrap Router into a coroutine to fix TestClient's bad introspection
    async def app(scope: Scope, receive: Receive, send: Send) -> None:
        await router(scope, receive, send)

    return TestClient(app)


async def homepage(scope: Scope, receive: Receive, send: Send) -> None:
    assert scope["method"] == "GET"
    await Response("homepage", media_type="text/plain")(scope, receive, send)


async def users(scope: Scope, receive: Receive, send: Send) -> None:
    assert scope["method"] == "GET"
    await Response("all users", media_type="text/plain")(scope, receive, send)


async def user(scope: Scope, receive: Receive, send: Send) -> None:
    assert scope["method"] == "GET"
    content = "user " + scope["path_params"]["username"]
    await Response(content, media_type="text/plain")(scope, receive, send)


async def user_me(scope: Scope, receive: Receive, send: Send) -> None:
    assert scope["method"] == "GET"
    content = "user fixed me"
    await Response(content, media_type="text/plain")(scope, receive, send)


async def disable_user(scope: Scope, receive: Receive, send: Send) -> None:
    assert scope["method"] == "PUT"
    content = "user " + scope["path_params"]["username"] + " disabled"
    await Response(content, media_type="text/plain")(scope, receive, send)


async def user_no_match(scope: Scope, receive: Receive, send: Send) -> None:
    assert scope["method"] == "GET"
    content = "user fixed nomatch"
    await Response(content, media_type="text/plain")(scope, receive, send)


app = Router(
    [
        Route("/", homepage),
        Mount(
            "/users",
            Router(
                [
                    Route("", users),
                    Route("/me", user_me),
                    Route("/{username}", user),
                    Route("/{username}/disable", disable_user),
                    Route("/nomatch", user_no_match),
                ]
            ),
        ),
    ]
)


def test_router() -> None:
    client = get_client(app)
    response = client.get("/")
    assert response.status_code == 200
    assert response.text == "homepage"

    response = client.get("/foo")
    assert response.status_code == 404
    assert response.text == "Not Found"

    response = client.get("/users")
    assert response.status_code == 200
    assert response.text == "all users"

    response = client.get("/users/adriangb")
    assert response.status_code == 200
    assert response.text == "user adriangb"

    response = client.get("/users/me")
    assert response.status_code == 200
    assert response.text == "user fixed me"

    response = client.get("/users/adriangb/")
    assert response.status_code == 404
    assert response.text == "Not Found"

    response = client.put("/users/adriangb/disable")
    assert response.status_code == 200
    assert response.url == "http://testserver/users/adriangb/disable"
    assert response.text == "user adriangb disabled"

    response = client.get("/users/nomatch")
    assert response.status_code == 200
    assert response.text == "user fixed nomatch"


@pytest.mark.parametrize(
    "url,redirect",
    [
        ("/adrian", "http://testserver/adrian/"),
        ("/adrian?foo=bar", "http://testserver/adrian/?foo=bar"),
    ],
)
def test_redirect_slashes_to_slash(url: str, redirect: str) -> None:
    app = Router([Route("/{username}/", user)])

    client = get_client(app)

    resp = client.get(url, allow_redirects=False)
    assert resp.status_code == 307
    assert resp.headers["Location"] == redirect

    resp = client.get("/adrian/", allow_redirects=False)
    assert resp.status_code == 200
    assert resp.content == b"user adrian"


@pytest.mark.parametrize(
    "url,redirect",
    [
        ("/adrian/", "http://testserver/adrian"),
        ("/adrian/?foo=bar", "http://testserver/adrian?foo=bar"),
    ],
)
def test_redirect_slashes_from_slash(url: str, redirect: str) -> None:
    app = Router([Route("/{username}", user)])

    client = get_client(app)

    resp = client.get(url, allow_redirects=False)
    assert resp.status_code == 307
    assert resp.headers["Location"] == redirect

    resp = client.get("/adrian", allow_redirects=False)
    assert resp.status_code == 200
    assert resp.content == b"user adrian"


def test_redirect_slashes_with_matching_route() -> None:
    app = Router([Route("/{username}", user), Route("/{username}/", homepage)])

    client = get_client(app)

    resp = client.get("/adrian/", allow_redirects=False)
    assert resp.status_code == 200
    assert resp.content == b"homepage"

    resp = client.get("/adrian", allow_redirects=False)
    assert resp.status_code == 200
    assert resp.content == b"user adrian"


def test_redirect_slashes_root() -> None:
    app = Router([Route("/home", homepage)])

    client = get_client(app)

    resp = client.get("/", allow_redirects=False)
    assert resp.status_code == 404


@pytest.mark.parametrize("anyio_backend", ["asyncio"])
@pytest.mark.parametrize(
    "scope,expected_location",
    [
        (
            {"path": "/home/", "query_string": b"abc=123", "headers": []},
            "/home?abc=123",
        ),
        (
            {
                "scheme": "https",
                "server": ("example.com", 123),
                "path": "/home/",
                "query_string": b"abc=123",
                "headers": [],
            },
            "https://example.com:123/home?abc=123",
        ),
        (
            {
                "scheme": "https",
                "server": ("example.com", 443),
                "path": "/home/",
                "query_string": b"abc=123",
                "headers": [],
            },
            "https://example.com/home?abc=123",
        ),
        (
            {
                "scheme": "https",
                "path": "/home/",
                "query_string": b"abc=123",
                "headers": [(b"Authorization", b"Bearer"), (b"Host", b"example.com")],
            },
            "https://example.com/home?abc=123",
        ),
    ],
)
async def test_redirect_from_scope(
    scope: Message, expected_location: str, anyio_backend: Any
):
    scope.update({"type": "http"})

    app = Router([Route("/home", homepage)])

    async def rcv() -> Message:
        assert False, "should not be called"  # pragma: no cover

    responses: List[Message] = []

    async def send(message: Message) -> None:
        if message["type"] == "http.response.start":
            responses.append(message)

    await app(
        scope,
        rcv,
        send,
    )
    resp = responses.pop()
    assert resp["status"] == 307
    location = Headers(raw=[(k.lower(), v.lower()) for k, v in resp["headers"]])[
        "Location"
    ]
    assert location == expected_location


def test_lifespan() -> None:
    """Lifespans are propagated to all routes"""
    lifespans: Set[int] = set()

    @asynccontextmanager
    async def lifespan_1(*args: Any) -> AsyncIterator[None]:
        lifespans.add(1)
        yield

    @asynccontextmanager
    async def lifespan_2(*args: Any) -> AsyncIterator[None]:
        lifespans.add(2)
        yield

    app1 = Starlette(lifespan=lifespan_1)
    app2 = Starlette(lifespan=lifespan_2)

    app = Router([Route("/1", app1), Route("/2", app2)])

    client = get_client(app)

    with client:
        pass

    assert lifespans == {1, 2}
