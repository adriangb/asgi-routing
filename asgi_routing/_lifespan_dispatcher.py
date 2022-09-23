from typing import Iterable, List, Optional, Tuple

from starlette.types import ASGIApp, Message, Receive, Scope, Send


class LifespanExceptions(Exception):
    def __init__(self, exceptions: Iterable[Tuple[Exception, Optional[str]]]) -> None:
        self.exceptions = exceptions


class LifespanDispatcher:
    def __init__(self, apps: Iterable[ASGIApp]) -> None:
        self.apps = apps

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        assert scope["type"] == "lifespan"

        msg = await receive()
        assert msg["type"] == "lifespan.startup"

        apps = iter(self.apps)

        startup_completed = False
        excs: List[Tuple[Exception, Optional[str]]] = []

        async def handle_onion() -> None:
            nonlocal startup_completed
            center_of_onion = True
            while True:
                center_of_onion = False
                # call into the next app
                try:
                    app = next(apps)
                except StopIteration:
                    center_of_onion = True
                    break
                rcv, snd, sent, received = make_rcv_send()
                try:
                    await app(scope, rcv, snd)
                    break
                except Exception as exc:
                    if received:
                        failure_msg: Optional[str] = None
                        failed_message = next(
                            (
                                msg
                                for msg in sent
                                if msg["type"] == "lifespan.startup.failed"
                            ),
                            None,
                        )
                        if failed_message:
                            failure_msg = failed_message.get("message", None)
                        # app supports lifespans and raised an exception
                        excs.append((exc, failure_msg))
                        return
                    # lifespan not supported
                    continue
            if center_of_onion:
                await send({"type": "lifespan.startup.complete"})
                startup_completed = True
                msg = await receive()  # wait for server
                assert msg["type"] == "lifespan.shutdown"

        def make_rcv_send() -> Tuple[Receive, Send, List[Message], List[Message]]:
            received: List[Message] = []
            sent: List[Message] = []

            async def rcv() -> Message:
                if not received:
                    assert not sent
                    msg = {"type": "lifespan.startup"}
                    received.append(msg)
                    return msg
                assert received == [{"type": "lifespan.startup"}]
                assert sent == [{"type": "lifespan.startup.complete"}]
                await handle_onion()
                # shut down our wrapping apps
                msg = {"type": "lifespan.shutdown"}
                received.append(msg)
                return msg

            async def snd(msg: Message) -> None:
                if not sent:
                    assert received == [{"type": "lifespan.startup"}]
                    assert msg["type"] == "lifespan.startup.complete"
                    sent.append(msg)
                    return
                sent.append(msg)

            return rcv, snd, sent, received

        await handle_onion()
        if excs:
            if startup_completed:
                await send({"type": "lifespan.shutdown.failed"})
            else:
                await send({"type": "lifespan.startup.failed"})
            raise LifespanExceptions(excs)
        else:
            await send({"type": "lifespan.shutdown.complete"})
