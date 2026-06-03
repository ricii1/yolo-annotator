import datetime

from app import locks


def test_claim_lock_succeeds_when_free(conn, make_image, now):
    img = make_image()
    assert locks.claim_lock(conn, img, "sessionA", now, ttl=60) is True
    assert locks.lock_holder(conn, img, now) == "sessionA"


def test_other_session_cannot_claim_live_lock(conn, make_image, now):
    img = make_image()
    locks.claim_lock(conn, img, "sessionA", now, ttl=60)
    assert locks.claim_lock(conn, img, "sessionB", now, ttl=60) is False


def test_same_session_reclaim_is_allowed(conn, make_image, now):
    img = make_image()
    locks.claim_lock(conn, img, "sessionA", now, ttl=60)
    assert locks.claim_lock(conn, img, "sessionA", now, ttl=60) is True


def test_expired_lock_can_be_stolen(conn, make_image, now):
    img = make_image()
    locks.claim_lock(conn, img, "sessionA", now, ttl=60)
    later = now + datetime.timedelta(seconds=61)
    assert locks.claim_lock(conn, img, "sessionB", later, ttl=60) is True
    assert locks.lock_holder(conn, img, later) == "sessionB"


def test_lock_holder_is_none_when_expired(conn, make_image, now):
    img = make_image()
    locks.claim_lock(conn, img, "sessionA", now, ttl=60)
    later = now + datetime.timedelta(seconds=120)
    assert locks.lock_holder(conn, img, later) is None


def test_heartbeat_extends_only_for_owner(conn, make_image, now):
    img = make_image()
    locks.claim_lock(conn, img, "sessionA", now, ttl=60)
    mid = now + datetime.timedelta(seconds=30)
    assert locks.heartbeat(conn, img, "sessionA", mid, ttl=60) is True
    # Non-owner heartbeat is rejected.
    assert locks.heartbeat(conn, img, "sessionB", mid, ttl=60) is False
    # After extension the lock is still alive beyond the original expiry.
    past_original = now + datetime.timedelta(seconds=70)
    assert locks.lock_holder(conn, img, past_original) == "sessionA"


def test_release_frees_the_lock(conn, make_image, now):
    img = make_image()
    locks.claim_lock(conn, img, "sessionA", now, ttl=60)
    locks.release_lock(conn, img, "sessionA")
    assert locks.lock_holder(conn, img, now) is None


def test_release_by_non_owner_is_noop(conn, make_image, now):
    img = make_image()
    locks.claim_lock(conn, img, "sessionA", now, ttl=60)
    locks.release_lock(conn, img, "sessionB")
    assert locks.lock_holder(conn, img, now) == "sessionA"
