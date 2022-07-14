from starlette.responses import Response
from starlette.testclient import TestClient
from starlette.types import Receive, Scope, Send
from starlette.websockets import WebSocket

from asgi_routing import Mount, Route, Router


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


async def partial_ws_endpoint(scope: Scope, receive: Receive, send: Send) -> None:
    websocket = WebSocket(scope, receive, send)
    await websocket.accept()
    await websocket.send_json({"url": str(websocket.url)})
    await websocket.close()


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
    client = TestClient(app)
    response = client.get("/")
    assert response.status_code == 200
    assert response.text == "homepage"

    response = client.get("/foo")
    assert response.status_code == 404
    assert response.text == "Not Found"

    # # waiting for https://github.com/viz-rs/path-tree/pull/19
    # response = client.get("/users")
    # assert response.status_code == 200
    # assert response.text == "all users"

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
