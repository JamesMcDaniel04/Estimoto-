"""Bound photo request bytes before Starlette's multipart file spooling."""
from starlette.responses import JSONResponse

MAX_PHOTO_BODY = 11 * 1024 * 1024


class BodyTooLarge(Exception):
    pass


class PhotoBodyLimit:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        parts = scope.get("path", "").split("/")
        bounded_upload = (len(parts) == 5 and parts[1] == "v1" and
                          ((parts[2] == "estimates" and parts[4] == "photos") or
                           (parts[2] == "vehicles" and parts[4] == "image")))
        capture_upload = (len(parts) == 6 and parts[1:3] == ['v1', 'estimates']
                          and parts[4] == 'capture' and parts[5] in {'photos', 'guidance'})
        receipt_upload = (len(parts) == 6 and parts[1:4] == ['v1', 'knowledge', 'records'] and parts[5] == 'receipts')
        bounded_upload = bounded_upload or capture_upload or receipt_upload
        body_limit = 8 * 1024 * 1024 + 4096 if capture_upload else MAX_PHOTO_BODY
        if scope["type"] != "http" or scope["method"] != "POST" or not bounded_upload:
            await self.app(scope, receive, send)
            return
        headers = dict(scope.get("headers", []))
        declared = headers.get(b"content-length")
        if declared is not None:
            try:
                if int(declared) > body_limit:
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
                if consumed > body_limit:
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
