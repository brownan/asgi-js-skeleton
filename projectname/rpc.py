from __future__ import annotations

import asyncio
import json
import uuid
import weakref
from logging import getLogger
from typing import Any, Awaitable, Callable, Dict, MutableSet, Optional, cast

from projectname import asgitypes

logger = getLogger("pytimeviz.rpc")


class RPCError(Exception):
    pass


clients: MutableSet[Application] = weakref.WeakSet()

RpcMethod = Callable[..., Awaitable]

RPC_METHODS: Dict[str, RpcMethod] = {}


def rpc_method(name: str) -> Callable[[RpcMethod], RpcMethod]:
    def decorator(f: RpcMethod) -> RpcMethod:
        RPC_METHODS[name] = f
        return f

    return decorator


class Application:
    """Each instance of this class is a connection to a client"""

    def __init__(
        self,
        scope: asgitypes.Scope,
        receive: asgitypes.ASGIReceiveCallable,
        send: asgitypes.ASGISendCallable,
    ):
        self.scope = scope
        self.receive = receive
        self.send = send

        self.encoder = json.JSONEncoder(separators=(",", ":"))

        # Holds pending RPC calls that the python side has made to the JS but has not
        # yet received a response
        self.rpc_calls: Dict[str, asyncio.Future[Any]] = {}

    @classmethod
    def app(
        cls,
        scope: asgitypes.Scope,
        receive: asgitypes.ASGIReceiveCallable,
        send: asgitypes.ASGISendCallable,
    ) -> Awaitable:
        app = cls(scope, receive, send)
        return app.handle()

    async def send_json(self, obj: Any) -> None:
        await self.send(dict(type="websocket.send", text=self.encoder.encode(obj)))

    async def handle(self) -> None:
        connect_event = await self.receive()
        if connect_event["type"] == "websocket.connect":
            connect_event = cast(asgitypes.WebSocketConnectEvent, connect_event)
            await self.send(
                dict(
                    type="websocket.accept",
                )
            )
        else:
            raise RuntimeError("Websocket did not receive the 'connect' event")

        closed = False
        clients.add(self)
        try:
            while True:
                event = await self.receive()
                if event["type"] == "websocket.disconnect":
                    closed = True
                    break
                elif event["type"] == "websocket.receive":
                    event = cast(asgitypes.WebSocketReceiveEvent, event)
                    event_bytes = event.get("bytes")
                    event_text = event.get("text")
                    if event_bytes:
                        text = event_bytes.decode("utf-8")
                    elif event_text:
                        text = event_text
                    else:
                        raise ValueError("No receive event body")
                    await self.dispatch_message(text)
                else:
                    raise RuntimeError("Unknown websocket receive event")
        finally:
            clients.remove(self)
            if not closed:
                await self.send(
                    dict(
                        type="websocket.close",
                    )
                )

    async def dispatch_message(self, data: str) -> None:
        logger.debug(f"Message received: {data}")
        msg = json.loads(data)
        msg_type = msg.get("type")
        if msg_type == "response":
            self.handle_rpc_response(msg)
        elif msg_type == "request":
            asyncio.create_task(self.handle_rpc_request(msg))
        else:
            logger.warning(f"Unknown message type: {msg_type}")

    async def _send_rpc_response(
        self, call_id: str, retval: Optional[Any], error: Optional[str]
    ) -> None:
        logger.debug(f"Sending response to {call_id}: {retval!r} {error!r}")
        await self.send_json(
            dict(
                type="response",
                callId=call_id,
                retval=retval,
                error=error,
            )
        )

    async def handle_rpc_request(self, message: dict) -> None:
        logger.debug(f"Handling rpc request: {message}")
        call_id = message["callId"]
        name = message["name"]
        args = message["args"]

        method = RPC_METHODS.get(name)
        if method is None:
            await self._send_rpc_response(
                call_id, retval=None, error=f"No such method name {name!r}"
            )
            return

        try:
            retval = await method(self, *args)
        except Exception as e:
            logger.exception("Unhandled exception in rpc handler method")
            await self._send_rpc_response(call_id, retval=None, error=str(e))
        else:
            await self._send_rpc_response(call_id, retval=retval, error=None)

    def handle_rpc_response(self, message: dict) -> None:
        logger.debug(f"Handling rpc response: {message}")
        call_id = message["callId"]
        ret_val = message.get("retVal")
        error = message.get("error")

        fut = self.rpc_calls.pop(call_id)
        if error:
            fut.set_exception(RPCError(error))
        else:
            fut.set_result(ret_val)

    async def call_rpc(self, name: str, *args: Any) -> Any:
        call_id = str(uuid.uuid4())
        data = dict(
            type="request",
            callId=call_id,
            name=name,
            args=args,
        )
        fut: asyncio.Future = asyncio.Future()
        self.rpc_calls[call_id] = fut
        await self.send_json(data)
        return await fut
