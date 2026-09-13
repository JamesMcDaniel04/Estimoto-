"""Bound photo request bytes before Starlette's multipart file spooling."""
from starlette.responses import JSONResponse

MAX_PHOTO_BODY = 11 * 1024 * 1024


class BodyTooLarge(Exception):
    pass


class PhotoBodyLimit:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if (scope["type"] != "http" or scope["method"] != "POST" or
                len(parts := scope["path"].split("/")) != 5 or
                parts[1:3] != ["v1", "estimates"] or parts[4] != "photos"):
            await self.app(scope, receive, send)
            return
        headers = dict(scope.get("headers", []))
        declared = headers.get(b"content-length")
        if declared is not None:
            try:
                if int(declared) > MAX_PHOTO_BODY:
                    await JSONResponse({"detail": "Photo upload is too large."}, status_code=413)(scope, receive, send)
                    return
            except ValueError:
                await JSONResponse({"detail": "Invalid Content-Length."}, status_code=400)(scope, receive, send)
                return
        consumed = 0
        started = False

        async def capped_receive():
            nonlocal consumed
            message = await receive()
            if message["type"] == "http.request":
                consumed += len(message.get("body", b""))
                if consumed > MAX_PHOTO_BODY:
                    raise BodyTooLarge()
            return message

        async def tracking_send(message):
            nonlocal started
            if message["type"] == "http.response.start":
                started = True
            await send(message)

        try:
            await self.app(scope, capped_receive, tracking_send)
        except BodyTooLarge:
            if not started:
                await JSONResponse({"detail": "Photo upload is too large."}, status_code=413)(scope, receive, send)
