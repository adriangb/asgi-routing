from contextlib import asynccontextmanager
from typing import Any, AsyncIterator, Set

import pytest
from starlette.applications import Starlette
from starlette.testclient import TestClient
from starlette.types import Receive, Scope, Send

from asgi_routing import LifespanExceptions, Route, Router


def get_client(router: Router) -> TestClient:
    # Wrap Router into a coroutine to fix TestClient's bad introspection
    async def app(scope: Scope, receive: Receive, send: Send) -> None:
        await router(scope, receive, send)

    return TestClient(app)


def test_happy_path() -> None:
    # happy path: two apps that support lifespans
    lifespans: Set[int] = set()

    @asynccontextmanager
    async def lifespan_1(*args: Any) -> AsyncIterator[None]:
        lifespans.add(1)
        yield

    @asynccontextmanager
    async def lifespan_2(*args: Any) -> AsyncIterator[None]:
        lifespans.add(2)
        yield

    apps = [
        Route("/foo", Starlette(lifespan=lifespan_1)),
        Route("/bar", Starlette(lifespan=lifespan_2)),
    ]

    app = Router(apps)

    with get_client(app):
        pass

    assert lifespans == {1, 2}


def test_one_app_does_not_support_lifespans() -> None:
    # one app doesn't support lifespans
    # it shouldn't matter which one
    lifespans: Set[int] = set()

    @asynccontextmanager
    async def lifespan_1(*args: Any) -> AsyncIterator[None]:
        lifespans.add(1)
        yield

    async def app_does_not_support_lifespan(*args: Any) -> None:
        raise ValueError

    apps = [
        Route("/foo", app_does_not_support_lifespan),
        Route("/bar", Starlette(lifespan=lifespan_1)),
        Route("/baz", app_does_not_support_lifespan),
    ]

    app = Router(apps)

    with get_client(app):
        pass

    assert lifespans == {1}


def test_one_app_fails_to_start() -> None:
    # one app fails to start
    # order should not matter

    lifespans: Set[int] = set()

    @asynccontextmanager
    async def lifespan_1(*args: Any) -> AsyncIterator[None]:
        lifespans.add(1)
        yield
        lifespans.add(2)

    @asynccontextmanager
    async def lifespan_3(*args: Any) -> AsyncIterator[None]:
        raise ValueError
        yield

    apps = [
        Route("/foo", Starlette(lifespan=lifespan_3)),
        Route("/bar", Starlette(lifespan=lifespan_1)),
        Route("/baz", Starlette(lifespan=lifespan_3)),
    ]

    app = Router(apps)

    with pytest.raises(LifespanExceptions):
        with get_client(app):
            pass

    # we either ran it or not
    assert lifespans in (set(), {1, 2})


def test_one_app_fails_to_shutdown_1() -> None:
    # one app fails to shutdown
    # order should not matter
    lifespans: Set[int] = set()

    @asynccontextmanager
    async def lifespan_1(*args: Any) -> AsyncIterator[None]:
        lifespans.add(1)
        yield

    @asynccontextmanager
    async def lifespan_4(*args: Any) -> AsyncIterator[None]:
        yield
        raise ValueError

    apps = [
        Route("/foo", Starlette(lifespan=lifespan_4)),
        Route("/bar", Starlette(lifespan=lifespan_1)),
        Route("/baz", Starlette(lifespan=lifespan_4)),
    ]

    app = Router(apps)

    started = False

    with pytest.raises(LifespanExceptions):
        with get_client(app):
            started = True

    assert started

    assert lifespans == {1}


def test_one_app_fails_to_shutdown_2() -> None:
    # one lifespan fails to shutdown
    # but the other one should still run without exceptions
    lifespans: Set[int] = set()

    @asynccontextmanager
    async def lifespan_5(*args: Any) -> AsyncIterator[None]:
        yield
        raise ValueError

    @asynccontextmanager
    async def lifespan_6(*args: Any) -> AsyncIterator[None]:
        yield
        lifespans.add(6)

    apps = [
        Starlette(lifespan=lifespan_5),
        Starlette(lifespan=lifespan_6),
    ]

    apps = [
        Route("/foo", Starlette(lifespan=lifespan_5)),
        Route("/bar", Starlette(lifespan=lifespan_6)),
        Route("/foo", Starlette(lifespan=lifespan_5)),
    ]

    app = Router(apps)

    started = False

    with pytest.raises(LifespanExceptions):
        with get_client(app):
            started = True

    assert started
    assert lifespans == {6}


def test_error_propagates_to_server() -> None:
    """Errors in any lifespan propagate up"""

    class MyExc(Exception):
        pass

    @asynccontextmanager
    async def lifespan(*args: Any) -> AsyncIterator[None]:
        raise MyExc
        yield

    inner = Starlette(lifespan=lifespan)

    app = Router([Route("/", inner)])

    client = get_client(app)

    with pytest.raises(LifespanExceptions):
        with client:
            pass
