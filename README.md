# asgi-routing

Fast & flexible ASGI router.

## Example

We'll be using Starlette's `Response` object to handle some ASGI boilerplate that is not relevant to this example.

```python
from starlette.responses import Response

from asgi_routing import Mount, Route, Router


app = Router(
    [
        Route("/", homepage),
        Mount(
            "/users",
            Router(
                [
                    Route("/me", user_me),
                    Route("/{username}", user),
                    Route("/{username}/disable", disable_user),
                    Route("/nomatch", user_no_match),
                ]
            ),
        ),
    ]
)
```
