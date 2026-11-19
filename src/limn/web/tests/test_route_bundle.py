"""Route bundles preserve dispatch order and reject ambiguous keyed routes."""

import unittest

from limn.web.routes import PostDocRoute, RouteBundle, merge_routes


def _get(_request):
    return None


def _post_document(_request):
    return {}, 200


def _pin_action(_request):
    return {}


def _other_post(_request):
    return {}


class RouteBundleTests(unittest.TestCase):
    """Composition combines ordered fallthrough routes and unique keyed routes."""

    def test_merge_preserves_get_and_document_post_order(self) -> None:
        """GET fallthrough and document POST registration retain capability order."""
        first = RouteBundle(get=(_get,), post_documents=(PostDocRoute("/one", _post_document),))
        second = RouteBundle(get=(_get,), post_documents=(PostDocRoute("/two", _post_document, True),))

        merged = merge_routes(first, second)

        self.assertEqual(merged.get, (_get, _get))
        self.assertEqual([route.path for route in merged.post_documents], ["/one", "/two"])

    def test_merge_keeps_packaged_reads_apart_and_in_order(self) -> None:
        """Packaged reads merge in capability order into their own group; a computed read never moves into it."""

        def packaged_one(_request):
            return None

        def packaged_two(_request):
            return None

        merged = merge_routes(
            RouteBundle(get_packaged=(packaged_one,)),
            RouteBundle(get=(_get,)),
            RouteBundle(get_packaged=(packaged_two,)),
        )

        self.assertEqual(merged.get_packaged, (packaged_one, packaged_two))
        self.assertEqual(merged.get, (_get,))
        self.assertEqual(RouteBundle(get=(_get,)).get_packaged, ())

    def test_duplicate_keyed_routes_are_rejected(self) -> None:
        """No later capability silently shadows a registered mutation route."""
        cases = (
            (
                RouteBundle(post_documents=(PostDocRoute("/same", _post_document),)),
                RouteBundle(post_documents=(PostDocRoute("/same", _post_document, True),)),
            ),
            (
                RouteBundle(pin_actions={"same": _pin_action}),
                RouteBundle(pin_actions={"same": _pin_action}),
            ),
            (
                RouteBundle(other_posts={"/same": _other_post}),
                RouteBundle(other_posts={"/same": _other_post}),
            ),
        )
        for first, second in cases:
            with self.subTest(first=first), self.assertRaises(ValueError):
                merge_routes(first, second)
