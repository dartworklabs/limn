"""HTTP paths and complete replies for pin lists, single pins, Trash and pins.md."""

import re
from collections.abc import Callable

from limn.pins.listing import http
from limn.pins.listing.http import ListingApp
from limn.web.reply import Reply, json_reply
from limn.web.routes import GetRequest


def get(
    request: GetRequest,
    app: ListingApp,
    maybe_purge_trash: Callable[[], int],
    remote_base_for: Callable[[str], str],
) -> Reply | None:
    """Answer a pin read route with its existing Trash cleanup and remote-base order."""
    path = request.path
    if path == "/pins.md":
        maybe_purge_trash()
        base = remote_base_for(request.host_raw)
        return Reply(200, http.markdown(app, base).encode("utf-8"), "text/markdown; charset=utf-8")
    if path == "/api/pins":
        maybe_purge_trash()
        return json_reply(http.pins(app, request.query, request.doc.key))
    if path == "/api/pins/dropped":
        return json_reply(http.dropped(app))
    match = re.fullmatch(r"/api/pins/(\d+)", path)
    if match:
        return json_reply(http.one(app, int(match.group(1))))
    return None
