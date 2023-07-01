"""Really simple static files serving"""
import datetime
import mimetypes
from email.utils import parsedate
from hashlib import md5
from pathlib import Path
from typing import Iterable, List, Optional, Tuple, cast

import aiofiles.os

from projectname import asgitypes

STATIC_DIR = (Path(__file__).parent / "static").resolve()


async def _send_http_response(
    send: asgitypes.ASGISendCallable,
    status: int,
    headers: Optional[Iterable[Tuple[bytes, bytes]]] = None,
    body: Optional[bytes] = None,
) -> None:
    await send(
        dict(
            type="http.response.start",
            status=status,
            headers=headers or [],
        )
    )
    body = body or b""
    await send(
        dict(
            type="http.response.body",
            body=body,
            more_body=False,
        )
    )


async def static_files_app(
    scope: asgitypes.Scope,
    receive: asgitypes.ASGIReceiveCallable,
    send: asgitypes.ASGISendCallable,
) -> None:
    scope = cast(asgitypes.HTTPScope, scope)

    path = scope.get("path")
    if not path or path == "/":
        abspath = Path("static/index.html").resolve()
    else:
        abspath = (STATIC_DIR / path).resolve()
        if not abspath.is_relative_to(STATIC_DIR):
            await _send_http_response(
                send, 404, [(b"Content-Type", b"text/plain")], body=b"NOT FOUND"
            )
            return

    req_headers = {k.decode("ascii").lower(): v for k, v in scope["headers"]}

    headers: List[Tuple[bytes, bytes]] = []

    content_type, encoding = mimetypes.guess_type(abspath)
    if not content_type:
        content_type = "application/octet-stream"
    if content_type.startswith("text/"):
        headers.append(
            (b"Content-Type", content_type.encode("ascii") + b"; charset=utf-8")
        )
    else:
        headers.append((b"Content-Type", content_type.encode("ascii")))

    if encoding:
        headers.append((b"Content-Encoding", encoding.encode("ascii")))

    stat_result = await aiofiles.os.stat(abspath)
    file_size = str(stat_result.st_size).encode("ascii")
    last_modified = datetime.datetime.fromtimestamp(stat_result.st_mtime).strftime(
        "%a, %d %b %Y %H:%M:%S GMT"
    )
    last_modified_enc = last_modified.encode("ascii")
    headers.append((b"Last-Modified", last_modified_enc))

    etag = md5(file_size + last_modified_enc).hexdigest().encode("ascii")
    headers.append((b"ETag", etag))

    previous_etag = req_headers.get("if-none-match")
    if previous_etag and previous_etag == etag:
        await _send_http_response(send, 304, headers=headers)
        return
    last_requested = req_headers.get("if-modified-since")
    if last_requested:
        last_req_parsed = parsedate(last_requested.decode("ascii"))
        last_mod_parsed = parsedate(last_modified)
        if last_req_parsed and last_mod_parsed and last_req_parsed >= last_mod_parsed:
            await _send_http_response(send, 304, headers=headers)
            return

    headers.append((b"Content-Length", file_size))

    await send(
        dict(
            type="http.response.start",
            status=200,
            headers=headers,
        )
    )

    async with aiofiles.open(abspath, mode="rb") as f:
        more_body = True
        while more_body:
            data = await f.read(65535)
            more_body = len(data) == 65535
            await send(
                dict(
                    type="http.response.body",
                    body=data,
                    more_body=more_body,
                )
            )
