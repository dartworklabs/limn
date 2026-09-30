"""Shared pin context contracts: actor normalization, record lookup and dependency boundaries."""

import ast
import unittest
from pathlib import Path

from limn.pins import context as service
from limn.pins.context import LoadedPin, is_agent, load_pin, typed_actor, who
from limn.pins.model import Agent, Person, PinNotFound, ReviewPin, parse_pin

from helpers_access import ALICE_ACTOR
from helpers_pin_service import AGENT

SERVICE_PATH = Path(service.__file__)


class ModuleBoundary(unittest.TestCase):
    """The pin context sits below the composition root: no server import, no run settings, no clock of its own."""

    def modules(self):
        """(file name, set of imported module names, set of Name ids) for every module of the package."""
        out = []
        for f in (SERVICE_PATH,):
            tree = ast.parse(f.read_text(encoding="utf-8"))
            mods = {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
            mods |= {n.module or "" for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
            names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
            out.append((f.name, mods, names))
        return out

    def test_imports_no_server_http_or_clock(self):
        """No module imports server.py, the HTTP layer, subprocess or a clock (time, datetime): those come in the context."""
        for name, mods, _ in self.modules():
            with self.subTest(name):
                self.assertFalse({m for m in mods if m.startswith(("limn.server", "limn.web", "server"))}, mods)
                self.assertFalse({"time", "datetime", "subprocess", "http", "http.server", "urllib"} & mods, mods)

    def test_reads_no_server_global(self):
        """No run-argument object, server lock or server helper is named in the package."""
        for name, _, names in self.modules():
            with self.subTest(name):
                self.assertFalse(
                    names
                    & {
                        "C",
                        "DOCS",
                        "PIN_LOCK",
                        "now_str",
                        "pin_store",
                        "transact",
                        "THREAD_MAX",
                        "TRASH_DAYS",
                        "_TRASH_CHECKED",
                        "make_docs",
                        "cur_doc",
                    }
                )


class Actors(unittest.TestCase):
    """is_agent and typed_actor: who a request's actor dict is to the rules."""

    def test_headerless_and_token_actors_are_agents(self):
        """login 'local' (also the default) and 'agent:<name>' are agents; a person's login is not."""
        self.assertTrue(is_agent(AGENT))
        self.assertTrue(is_agent({}))
        self.assertTrue(is_agent(None))
        self.assertTrue(is_agent({"login": "agent:ci", "name": "ci"}))
        self.assertFalse(is_agent(ALICE_ACTOR))

    def test_typed_actor_keeps_a_picture_only_when_it_is_text(self):
        """An agent becomes Agent; a person Person with pic only for a non-empty string."""
        self.assertEqual(typed_actor({"login": "agent:ci", "name": "ci"}), Agent("agent:ci", "ci"))
        self.assertEqual(
            typed_actor(dict(ALICE_ACTOR, pic="https://example.com/a.png")),
            Person("alice@example.com", "Alice Kim", "https://example.com/a.png"),
        )
        self.assertEqual(typed_actor(dict(ALICE_ACTOR, pic="")), Person("alice@example.com", "Alice Kim", None))


class LoadPin(unittest.TestCase):
    """load_pin: the one lookup by id every pin action's transact() step starts with."""

    def test_a_found_pin_comes_back_with_its_position(self):
        """The first pin with the id comes back by identity with its position (where a step puts its next state)."""
        pins = [parse_pin({"id": 1, "done": False}), parse_pin({"id": 2, "done": True, "review": True})]
        pins.append(parse_pin({"id": 2}))
        found = load_pin(pins, 2)
        self.assertIsInstance(found, LoadedPin)
        self.assertEqual(found.pos, 1)
        self.assertIs(found.pin, pins[1])
        self.assertIsInstance(found.pin, ReviewPin)
        pos, pin = found
        self.assertEqual((pos, pin), (1, pins[1]))

    def test_a_missing_id_is_a_named_miss(self):
        """No pin with the id is PinNotFound carrying that id, never None."""
        self.assertEqual(load_pin([parse_pin({"id": 1})], 3), PinNotFound(3))
        self.assertEqual(load_pin([], 1), PinNotFound(1))


class Who(unittest.TestCase):
    """who: an actor as notices and audit.jsonl record it."""

    def test_login_and_name_only_with_the_local_defaults(self):
        """A person keeps login and name (never pic or role); an empty actor is the headerless loopback agent."""
        self.assertEqual(
            who({"login": "alice@example.com", "name": "Alice", "pic": "https://x", "role": "owner"}),
            {"login": "alice@example.com", "name": "Alice"},
        )
        self.assertEqual(who({}), {"login": "local", "name": ""})
        actor = {"login": "agent:ci", "name": "ci"}
        self.assertIsNot(who(actor), actor)
