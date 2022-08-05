# asgi-routing

A high performance router written in 🦀 for the ASGI ecosystem.
Built on top of [routrie] and [path-tree].

[routrie]: https://github.com/adriangb/routrie
[path-tree]: https://github.com/viz-rs/path-tree

## Features

* Pure ASGI, compatible with any ASGI web framework.
* Very fast, we use a radix-tree router written in Rust.
* Support for all of the common routing primitives like path parameters and catch-all parameters.

## Example

We'll be using Starlette's `Response` object to handle some ASGI boilerplate that is not relevant to this example.

```python
from starlette.responses import PlainTextResponse

from asgi_routing import Mount, Route, Router


app = Router(
    [
        Route("/", PlainTextResponse("home")),
        Mount(
            "/users",
            Router(
                [
                    Route("/me", PlainTextResponse("me")),
                    Route("/{username}", PlainTextResponse("you")),
                    Route("/{username}/disable", PlainTextResponse("bye")),
                    Route("/nomatch", PlainTextResponse("who?")),
                ]
            ),
        ),
    ]
)
```

Since this is a pure ASGI router, you can also mount it to a specific path in a Starlette app if you know that that path is high traffic or has a very large routing table.
You won't see much of a difference compared to Starlette's built in router unless you have 20+ routes.
See [benchmarks] for more details.

[benchmarks]: https://github.com/xpresso-devs/asgi-routing/blob/main/bench.ipynb
