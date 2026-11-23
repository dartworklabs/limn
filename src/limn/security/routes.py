"""HTTP paths and replies of the owner's access routes."""

from limn.security import http
from limn.security.http import AccessWiring
from limn.web.reply import Reply, json_reply
from limn.web.routes import GetRequest, OtherPost, RouteBundle

ACCESS_PATH = "/api/access"


def get(request: GetRequest, wiring: AccessWiring) -> Reply | None:
    """Answer the owner's access view; check_read has already refused every other role. The reader's own login and
    principal go in because the view says, before the press, whether turning management off would shut them out."""
    if request.path == ACCESS_PATH:
        login = request.actor.get("login")
        return json_reply(http.access_view(wiring, login if type(login) is str else "", request.principal))
    return None


def routes(wiring: AccessWiring) -> RouteBundle:
    """Bind the access read and the four member POSTs to this run. Registering a path here grants it nothing: the
    paths are declared in access.MEMBER_OPERATIONS, which the guard consults first."""
    posts: dict[str, OtherPost] = {
        "/api/access/managed": lambda r: http.set_managed(wiring, r.actor, r.body),
        "/api/members/add": lambda r: http.member_add(wiring, r.actor, r.body),
        "/api/members/role": lambda r: http.member_role(wiring, r.actor, r.body),
        "/api/members/remove": lambda r: http.member_remove(wiring, r.actor, r.body),
    }
    return RouteBundle(get=(lambda request: get(request, wiring),), other_posts=posts)
