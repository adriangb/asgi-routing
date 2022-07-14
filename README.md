# asgi-router

ASGI middlewate to support ASGI lifespans using a simple async context manager interface.

This middleware accepts an ASGI application to wrap and an async context manager lifespan.
It will run both the lifespan it was handed directly and that of the ASGI app (if the wrapped ASGI app supports lifespans).

## Example

```python

```