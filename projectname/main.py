from __future__ import annotations

import asyncio
import copy
import logging
import os.path
import sys
from contextlib import ExitStack
from typing import (
    Awaitable,
    Coroutine,
    Mapping,
    cast,
)

import ptpython
import uvicorn
import watchfiles
from prompt_toolkit.patch_stdout import patch_stdout

from projectname import asgitypes
from projectname.rpc import Application
from projectname.static import static_files_app

logger = logging.getLogger("projectname")

should_reload = False


async def file_watcher() -> None:
    global should_reload
    paths = [
        os.path.dirname(__file__),
    ]
    logger.info(f"Watching files for changes: {paths}")
    async for changes in watchfiles.awatch(*paths):
        print(f"Path changed: {list(changes)}")
        print("Restarting...")
        should_reload = True
        break


def protocol_router(
    application_mapping: Mapping[str, asgitypes.ASGI3Application]
) -> asgitypes.ASGI3Application:
    def router_app(
        scope: asgitypes.Scope,
        receive: asgitypes.ASGIReceiveCallable,
        send: asgitypes.ASGISendCallable,
    ) -> Awaitable:
        logger.debug(f"Routing request to protocol {scope['type']}")
        try:
            app = application_mapping[scope["type"]]
        except KeyError:
            raise ValueError(f"No application configured for scope type {scope['type']}")
        return app(scope, receive, send)

    return router_app


async def main(console: bool = False, watch: bool = False) -> None:
    with ExitStack() as context:
        if console:
            context.enter_context(patch_stdout(raw=True))

        logging_config = copy.deepcopy(uvicorn.config.LOGGING_CONFIG)
        logging_config["loggers"][logger.name] = {
            "level": "DEBUG",
            "handlers": ["default"],
        }

        config = uvicorn.Config(
            protocol_router(
                {
                    "http": static_files_app,
                    "websocket": Application.app,
                }
            ),
            interface="asgi3",
            port=8888,
            log_level="info",
            workers=1,
            log_config=logging_config,
        )
        server = uvicorn.Server(config)

        tasks = []
        if console:
            tasks.append(
                asyncio.create_task(
                    cast(
                        Coroutine,
                        ptpython.embed(globals=globals(), return_asyncio_coroutine=True),
                    )
                )
            )
        elif watch:
            tasks.append(asyncio.create_task(file_watcher()))

        tasks.append(asyncio.create_task(server.serve()))

        await asyncio.wait(
            tasks,
            return_when=asyncio.FIRST_COMPLETED,
        )

    await server.shutdown()
    if should_reload:
        os.execv(sys.executable, [sys.executable] + sys.argv)


if __name__ == "__main__":
    print("New process started")
    asyncio.run(main(console="--console" in sys.argv, watch="--watch" in sys.argv))
