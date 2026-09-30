"""Claims service and HTTP behavior over real pin storage and explicit collaborators."""

import json
import time
from unittest import mock

from limn.pins.claims import input as claims_input
from limn.pins.claims.rules import ClaimClosedPin, ClaimedByOther, NotClaimed
from limn.pins.claims.service import PinClaims
from limn.pins.lifecycle.rules import CloseRequest
from limn.pins.model import OpenPin, PinNotFound
from limn.pins.store import find_pin
from limn.pins.thread import CLAIM_FIELDS, claim_holds
from limn.security.access import LOCAL_ACTOR
from limn.web.errors import InputRejected

from helpers import (
    Base,
    find_record,
    ps,
    record_of,
    records,
    req,
    trash_records,
    write_records,
)
from helpers_access import BOB_ACTOR
from helpers_authority import post_authority
from helpers_pin_service import AGENT, ServiceBase, T

CLAIM_CLOCK = 1790384400.0


class Claims(ServiceBase):
    """claim_pin and unclaim_pin around limn.pins.claims.rules.claim/unclaim."""

    def test_another_identitys_live_claim_is_refused_without_writing(self):
        """The agent claims; Bob's claim is ClaimedByOther and the file keeps the agent's claim."""
        pid = self.add()
        self.assertIsInstance(
            PinClaims(lambda: self.ctx).claim_pin(
                pid, post_authority(PinClaims(lambda: self.ctx).context().store, AGENT, "claim", pid), 30
            ),
            OpenPin,
        )
        before = self.pins_bytes()
        self.assertIsInstance(
            PinClaims(lambda: self.ctx).claim_pin(
                pid, post_authority(PinClaims(lambda: self.ctx).context().store, BOB_ACTOR, "claim", pid), 30
            ),
            ClaimedByOther,
        )
        self.assertEqual(self.pins_bytes(), before)
        self.assertEqual(self.pin(pid)["claim_until"], T + 30 * 60)

    def test_unclaim_writes_only_when_there_was_a_claim(self):
        """unclaim clears the marker; a second unclaim is NotClaimed with the file unchanged."""
        pid = self.add()
        PinClaims(lambda: self.ctx).claim_pin(
            pid, post_authority(PinClaims(lambda: self.ctx).context().store, AGENT, "claim", pid), 30
        )
        self.assertIsInstance(
            PinClaims(lambda: self.ctx).unclaim_pin(
                pid, post_authority(PinClaims(lambda: self.ctx).context().store, BOB_ACTOR, "unclaim", pid)
            ),
            OpenPin,
        )
        self.assertNotIn("claimed_by", self.pin(pid))
        before = self.pins_bytes()
        self.assertIsInstance(
            PinClaims(lambda: self.ctx).unclaim_pin(
                pid, post_authority(PinClaims(lambda: self.ctx).context().store, BOB_ACTOR, "unclaim", pid)
            ),
            NotClaimed,
        )
        self.assertEqual(self.pins_bytes(), before)


class Claim(Base):
    """The claim service handles ownership conflicts, expiry, and revision changes."""

    def test_claim_sets_fields_and_bumps_rev(self):
        """An authorized claim persists its actor and increments revision while establishing a live lease."""
        pid = self.add()
        p = record_of(
            ps.APP.pin_claims.claim_pin(
                pid,
                post_authority(
                    ps.APP.pin_claims.context().store, {"login": "alice@example.com", "name": "Wendy"}, "claim", pid
                ),
                120,
            )
        )
        self.assertEqual(p["claimed_by"], {"login": "alice@example.com", "name": "Wendy"})
        self.assertEqual(p["rev"], 1)
        self.assertTrue(claim_holds(self.pin(pid), time.time()))

    def test_default_ttl_used_when_body_omits_it(self):
        """A claim body without ttl_min holds the pin for the default TTL from the moment of the claim (clock frozen)."""
        pid = self.add()
        before = CLAIM_CLOCK
        with mock.patch("time.time", return_value=before):
            p = record_of(
                ps.APP.pin_claims.claim_pin(
                    pid,
                    post_authority(ps.APP.pin_claims.context().store, dict(LOCAL_ACTOR), "claim", pid),
                    claims_input.parse_claim_body({}).ttl,
                )
            )
        self.assertEqual(p["claim_until"], before + claims_input.CLAIM_TTL_DEFAULT * 60)

    def test_claim_conflict_from_other_identity_is_409(self):
        """An active claim returns the current holder and expiry to a competing claimant."""
        pid = self.add()
        ps.APP.pin_claims.claim_pin(
            pid,
            post_authority(
                ps.APP.pin_claims.context().store, {"login": "alice@example.com", "name": "Wendy"}, "claim", pid
            ),
            120,
        )
        refused = ps.APP.pin_claims.claim_pin(
            pid,
            post_authority(
                ps.APP.pin_claims.context().store, {"login": "bob@example.com", "name": "Bob"}, "claim", pid
            ),
            120,
        )  # answered 409 "claimed"
        self.assertIsInstance(refused, ClaimedByOther)
        self.assertEqual(refused.claimed_by["login"], "alice@example.com")
        self.assertIsNotNone(refused.claim_until)

    def test_claim_same_identity_extends(self):
        """Reclaiming with the same identity extends the lease and advances revision instead of conflicting."""
        pid = self.add()
        first = record_of(
            ps.APP.pin_claims.claim_pin(
                pid,
                post_authority(
                    ps.APP.pin_claims.context().store, {"login": "alice@example.com", "name": "Wendy"}, "claim", pid
                ),
                5,
            )
        )
        second = record_of(
            ps.APP.pin_claims.claim_pin(
                pid,
                post_authority(
                    ps.APP.pin_claims.context().store, {"login": "alice@example.com", "name": "Wendy"}, "claim", pid
                ),
                200,
            )
        )
        self.assertGreater(second["claim_until"], first["claim_until"])
        self.assertEqual(second["rev"], first["rev"] + 1)

    def test_claim_on_closed_pin_is_409_done(self):
        """A completed pin returns ClaimClosedPin even when the caller holds valid claim authority."""
        pid = self.add()
        ps.APP.pin_lifecycle.close_pin(
            pid, post_authority(ps.APP.pin_lifecycle.context().store, dict(LOCAL_ACTOR), "close", pid), CloseRequest()
        )
        # 409 "done"
        self.assertIsInstance(
            ps.APP.pin_claims.claim_pin(
                pid,
                post_authority(
                    ps.APP.pin_claims.context().store, {"login": "alice@example.com", "name": "Wendy"}, "claim", pid
                ),
                120,
            ),
            ClaimClosedPin,
        )

    def test_claim_missing_pin_id_returns_none(self):
        """Claiming an absent id returns PinNotFound rather than creating a record or raising."""
        self.assertEqual(
            ps.APP.pin_claims.claim_pin(
                999, post_authority(ps.APP.pin_claims.context().store, dict(LOCAL_ACTOR), "claim", 999), 120
            ),
            PinNotFound(999),
        )

    def test_ttl_out_of_range_or_wrong_type_rejected(self):
        """The claim parser rejects invalid TTL values and clamps older oversized requests."""
        for bad in (0, -1, "120", 12.5, True, None):  # 400 for a wrong type or a value below 1
            self.assertIsInstance(claims_input.parse_claim_body({"ttl_min": bad}), InputRejected)
        self.assertEqual(claims_input.parse_claim_body({}).ttl, claims_input.CLAIM_TTL_DEFAULT)
        self.assertEqual(claims_input.parse_claim_body({"ttl_min": 1}).ttl, 1)
        self.assertEqual(claims_input.parse_claim_body({"ttl_min": 120}).ttl, 120)
        self.assertEqual(claims_input.CLAIM_TTL_MAX, 120)
        for over in (121, 480, 10_000):  # above the cap (120, formerly 480) it gets clamped down (backward compat)
            self.assertEqual(claims_input.parse_claim_body({"ttl_min": over}).ttl, 120)

    def test_expired_claim_is_inactive_and_can_be_reclaimed_by_another_identity(self):
        """Once the stored hold expires, another identity may claim the same pin."""
        pid = self.add()
        ps.APP.pin_claims.claim_pin(
            pid,
            post_authority(
                ps.APP.pin_claims.context().store, {"login": "alice@example.com", "name": "Wendy"}, "claim", pid
            ),
            120,
        )
        rows = records(ps.APP.snapshot_pins())
        for r in rows:
            if r["id"] == pid:
                r["claim_until"] = time.time() - 10
        write_records(rows)
        self.assertFalse(claim_holds(self.pin(pid), time.time()))
        p = record_of(
            ps.APP.pin_claims.claim_pin(
                pid,
                post_authority(
                    ps.APP.pin_claims.context().store, {"login": "bob@example.com", "name": "Bob"}, "claim", pid
                ),
                120,
            )
        )
        self.assertEqual(p["claimed_by"]["login"], "bob@example.com")

    def test_unclaim_clears_fields_regardless_of_requester(self):
        """Unclaim clears all hold fields even when a different person requests it."""
        pid = self.add()
        ps.APP.pin_claims.claim_pin(
            pid,
            post_authority(
                ps.APP.pin_claims.context().store, {"login": "alice@example.com", "name": "Wendy"}, "claim", pid
            ),
            120,
        )
        p = record_of(
            ps.APP.pin_claims.unclaim_pin(
                pid,
                post_authority(
                    ps.APP.pin_claims.context().store, {"login": "bob@example.com", "name": "Bob"}, "unclaim", pid
                ),
            )
        )
        self.assertNotIn("claimed_by", p)
        self.assertNotIn("claimed_at", p)
        self.assertNotIn("claim_until", p)

    def test_unclaim_missing_pin_returns_none(self):
        """Releasing an absent id returns PinNotFound and cannot manufacture a pin."""
        self.assertEqual(
            ps.APP.pin_claims.unclaim_pin(
                999, post_authority(ps.APP.pin_claims.context().store, dict(LOCAL_ACTOR), "unclaim", 999)
            ),
            PinNotFound(999),
        )

    def test_close_clears_claim(self):
        """Closing a claimed pin removes its active owner so finished work cannot remain reserved."""
        pid = self.add()
        ps.APP.pin_claims.claim_pin(
            pid, post_authority(ps.APP.pin_claims.context().store, dict(LOCAL_ACTOR), "claim", pid), 120
        )
        p = record_of(
            ps.APP.pin_lifecycle.close_pin(
                pid,
                post_authority(ps.APP.pin_lifecycle.context().store, dict(LOCAL_ACTOR), "close", pid),
                CloseRequest(),
            )
        )
        self.assertNotIn("claimed_by", p)

    def test_drop_clears_claim_even_in_dropped_record(self):
        """Deletion strips claim ownership from the persisted trash projection as well as the live list."""
        pid = self.add()
        ps.APP.pin_claims.claim_pin(
            pid, post_authority(ps.APP.pin_claims.context().store, dict(LOCAL_ACTOR), "claim", pid), 120
        )
        ps.APP.pin_trash.drop_pin(pid, post_authority(ps.APP.pin_trash.context().store, dict(LOCAL_ACTOR), "drop", pid))
        dropped = ps.APP.pin_listing.dropped_payload()
        self.assertEqual(len(dropped), 1)
        self.assertNotIn("claimed_by", dropped[0])

    def test_pins_md_shows_hourglass_with_claimer_name_and_legend(self):
        """Markdown names the active worker and explains skipping reserved work using words, not an hourglass."""
        pid = self.add()
        ps.APP.pin_claims.claim_pin(
            pid,
            post_authority(
                ps.APP.pin_claims.context().store, {"login": "kim@example.com", "name": "Coauthor Kim"}, "claim", pid
            ),
            120,
        )
        md = ps.APP.C.pins_md.read_text(encoding="utf-8")
        self.assertIn("처리 중(Coauthor Kim)", md)  # just the name when there's no ETA
        self.assertNotIn("⏳", md)
        self.assertIn("'처리 중(이름, 약 N분)' = 다른 에이전트가 잡음, 건너뛴다", md)

    def test_pins_md_hourglass_uses_local_label_for_curl_claims(self):
        """A loopback-agent lease uses the stable local/agent label in the Markdown contract."""
        pid = self.add()
        ps.APP.pin_claims.claim_pin(
            pid, post_authority(ps.APP.pin_claims.context().store, dict(LOCAL_ACTOR), "claim", pid), 120
        )
        md = ps.APP.C.pins_md.read_text(encoding="utf-8")
        self.assertIn("처리 중(로컬/에이전트)", md)

    def test_claim_fields_survive_jsonl_roundtrip(self):
        """Reading saved JSONL preserves claim attribution without treating the record as corrupt."""
        pid = self.add()
        ps.APP.pin_claims.claim_pin(
            pid,
            post_authority(
                ps.APP.pin_claims.context().store, {"login": "alice@example.com", "name": "Wendy"}, "claim", pid
            ),
            120,
        )
        pins, bad = ps.APP.read_pins()
        self.assertEqual(bad, [])
        self.assertIn("claimed_by", find_record(pins, pid))

    def test_http_claim_then_conflict_then_unclaim(self):
        pid = self.add()
        h1 = {"Host": "127.0.0.1:18999", "Tailscale-User-Login": "alice@example.com", "Tailscale-User-Name": "Wendy"}
        out = self.talk(req("POST", "/api/pins/%d/claim" % pid, headers=h1))
        self.assertIn(b" 200 ", out)
        h2 = {"Host": "127.0.0.1:18999", "Tailscale-User-Login": "bob@example.com", "Tailscale-User-Name": "Bob"}
        out = self.talk(req("POST", "/api/pins/%d/claim" % pid, headers=h2))
        self.assertIn(b" 409 ", out)
        body = json.loads(out.split(b"\r\n\r\n", 1)[1])
        self.assertEqual(body["claimed_by"]["login"], "alice@example.com")
        out = self.talk(req("POST", "/api/pins/%d/unclaim" % pid))
        self.assertIn(b" 200 ", out)
        self.assertFalse(claim_holds(self.pin(pid), time.time()))

    def test_http_claim_bad_ttl_type_is_400(self):
        pid = self.add()
        body = json.dumps({"ttl_min": "soon"}).encode()
        out = self.talk(req("POST", "/api/pins/%d/claim" % pid, body, {"Content-Type": "application/json"}))
        self.assertIn(b" 400 ", out)

    def test_http_claim_missing_pin_returns_ok_false(self):
        out = self.talk(req("POST", "/api/pins/999/claim"))
        self.assertIn(b" 200 ", out)
        body = json.loads(out.split(b"\r\n\r\n", 1)[1])
        self.assertFalse(body["ok"])


class ClaimEstimate(Base):
    """A claim with an estimate (eta_min) stores eta_ts and the start next to claim_until; the same identity extends it
    keeping the start, another identity is refused with the holder's estimate, and every way of ending the claim
    (close, drop, unclaim) clears all claim fields."""

    A = {"login": "alice@example.com", "name": "Wendy"}

    B = {"login": "bob@example.com", "name": "Bob"}

    def test_claim_stores_eta_and_start(self):
        """A claim with eta_min stores its start, its estimate and its deadline, all measured from the claim's moment
        (clock frozen)."""
        pid = self.add()
        t0 = CLAIM_CLOCK
        with mock.patch("time.time", return_value=t0):
            p = record_of(
                ps.APP.pin_claims.claim_pin(
                    pid,
                    post_authority(ps.APP.pin_claims.context().store, self.A, "claim", pid),
                    *claims_input.parse_claim_body({"eta_min": 15}),
                )
            )
        self.assertEqual(p["eta_ts"], t0 + 15 * 60)
        self.assertEqual(p["claim_ts"], t0)
        self.assertEqual(p["claim_until"], t0 + 30 * 60)
        self.assertIsInstance(p["claimed_at"], str)
        rows = records(ps.APP.read_pins()[0])  # it's a stored value (not a computed field)
        self.assertIn("eta_ts", find_pin(rows, pid))

    def test_same_identity_reclaim_extends_and_updates_estimate(self):
        """The same identity claiming again keeps the start and measures the new estimate and deadline from now (clock
        frozen); a claim with no estimate keeps the previous one."""
        pid = self.add()
        now = CLAIM_CLOCK
        with mock.patch("time.time", return_value=now):
            first = record_of(
                ps.APP.pin_claims.claim_pin(
                    pid,
                    post_authority(ps.APP.pin_claims.context().store, self.A, "claim", pid),
                    *claims_input.parse_claim_body({"eta_min": 5}),
                )
            )
            with ps.APP.RT.pin_lock:  # move it back to having been claimed 10 minutes ago
                rows = records(ps.APP.read_pins()[0])
                r = find_pin(rows, pid)
                for k in ("claim_ts", "eta_ts", "claim_until"):
                    r[k] -= 600
                write_records(rows)
            second = record_of(
                ps.APP.pin_claims.claim_pin(
                    pid,
                    post_authority(ps.APP.pin_claims.context().store, self.A, "claim", pid),
                    *claims_input.parse_claim_body({"eta_min": 20}),
                )
            )
            self.assertAlmostEqual(second["claim_ts"], first["claim_ts"] - 600, delta=1)  # the start time stays put
            self.assertEqual(second["claimed_at"], first["claimed_at"])
            self.assertEqual(second["eta_ts"], now + 20 * 60)  # the new estimate starts from now
            self.assertEqual(second["claim_until"], now + 40 * 60)
            # extending with no new estimate keeps the previous one
            third = record_of(
                ps.APP.pin_claims.claim_pin(
                    pid,
                    post_authority(ps.APP.pin_claims.context().store, self.A, "claim", pid),
                    *claims_input.parse_claim_body({}),
                )
            )
            self.assertEqual(third["eta_ts"], second["eta_ts"])
            self.assertEqual(third["rev"], second["rev"] + 1)

    def test_other_identity_conflict_reports_eta_and_new_claim_drops_old_eta(self):
        """Conflict reports the old ETA, but a later claimant never inherits that estimate."""
        pid = self.add()
        ps.APP.pin_claims.claim_pin(
            pid,
            post_authority(ps.APP.pin_claims.context().store, self.A, "claim", pid),
            *claims_input.parse_claim_body({"eta_min": 15}),
        )
        refused = ps.APP.pin_claims.claim_pin(
            pid,
            post_authority(ps.APP.pin_claims.context().store, self.B, "claim", pid),
            *claims_input.parse_claim_body({"eta_min": 5}),
        )  # answered 409 "claimed"
        self.assertIsInstance(refused, ClaimedByOther)
        self.assertIsNotNone(refused.eta_ts)
        with ps.APP.RT.pin_lock:  # A's claim has expired
            rows = records(ps.APP.read_pins()[0])
            find_pin(rows, pid)["claim_until"] = time.time() - 1
            write_records(rows)
        p = record_of(
            ps.APP.pin_claims.claim_pin(
                pid,
                post_authority(ps.APP.pin_claims.context().store, self.B, "claim", pid),
                *claims_input.parse_claim_body({}),
            )
        )
        self.assertEqual(p["claimed_by"]["login"], "bob@example.com")
        self.assertNotIn("eta_ts", p)  # doesn't inherit someone else's old estimate

    def test_close_drop_unclaim_clear_all_claim_fields(self):
        """Each terminal or release transition removes the complete claim and ETA field set."""
        for how in ("close", "drop", "unclaim"):
            pid = self.add()
            ps.APP.pin_claims.claim_pin(
                pid,
                post_authority(ps.APP.pin_claims.context().store, self.A, "claim", pid),
                *claims_input.parse_claim_body({"eta_min": 10}),
            )
            if how == "close":
                rec = record_of(
                    ps.APP.pin_lifecycle.close_pin(
                        pid, post_authority(ps.APP.pin_lifecycle.context().store, self.A, "close", pid), CloseRequest()
                    )
                )
            elif how == "unclaim":
                rec = record_of(
                    ps.APP.pin_claims.unclaim_pin(
                        pid, post_authority(ps.APP.pin_claims.context().store, self.A, "unclaim", pid)
                    )
                )
            else:
                ps.APP.pin_trash.drop_pin(pid, post_authority(ps.APP.pin_trash.context().store, self.A, "drop", pid))
                rec = trash_records()[-1]
            for k in CLAIM_FIELDS:
                self.assertNotIn(k, rec, (how, k))
