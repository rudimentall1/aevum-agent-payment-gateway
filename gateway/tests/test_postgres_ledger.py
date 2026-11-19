import os
from types import SimpleNamespace

import pytest
from cryptography.fernet import Fernet

from gateway.postgres_ledger import PostgresPaymentStore


DATABASE_URL = os.getenv("AEVUMPAY_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="PostgreSQL integration URL is not configured")


def payment(request_id="0x" + "11" * 32):
    return SimpleNamespace(
        request_id=request_id,
        intent_id="intent-1",
        payer="0x0000000000000000000000000000000000000001",
        recipient="0x0000000000000000000000000000000000000002",
    )


def test_payment_record_is_durable_and_duplicate_request_is_rejected():
    store = PostgresPaymentStore(DATABASE_URL, Fernet.generate_key())
    store.reset_for_test()
    req = payment()
    store.reserve(req, 1_250_000)

    restarted = PostgresPaymentStore(DATABASE_URL, store.cipher._signing_key and store.cipher._encryption_key)
    record = restarted.get(req.request_id)
    assert record["status"] == "AUTHORIZING"
    assert record["amount_base_units"] == "1250000"

    with pytest.raises(Exception):
        store.reserve(req, 1_250_000)


def test_signed_transaction_and_consume_marker_are_atomic_and_durable():
    key = Fernet.generate_key()
    store = PostgresPaymentStore(DATABASE_URL, key)
    store.reset_for_test()
    req = payment()
    store.reserve(req, 99)
    nonce = store.reserve_nonce(44005, "0x000000000000000000000000000000000000aE01", 17, req.request_id)
    assert nonce == 17

    raw = b"exact-signed-transaction-bytes"
    store.set_signed_transaction(req.request_id, "0x" + "ab" * 32, raw, 44005,
                                  "0x000000000000000000000000000000000000aE01", nonce)
    signed = store.get(req.request_id)
    assert signed["status"] == "SIGNED_AWAITING_CONSUME"
    assert store.cipher.decrypt(signed["raw_transaction"]) == raw

    restarted = PostgresPaymentStore(DATABASE_URL, key)
    restarted.update(req.request_id, "AUTHORIZED_CONSUMED")
    record = restarted.get(req.request_id)
    assert record["authorization_consumed"] is True
    assert record["status"] == "AUTHORIZED_CONSUMED"
    assert record["raw_transaction"] == signed["raw_transaction"]


def test_nonce_reservation_requires_existing_payment_and_survives_restart():
    store = PostgresPaymentStore(DATABASE_URL, Fernet.generate_key())
    store.reset_for_test()
    executor = "0x000000000000000000000000000000000000aE02"
    with pytest.raises(ValueError, match="payment"):
        store.reserve_nonce(44005, executor, 3, "missing-payment")

    req = payment("0x" + "22" * 32)
    store.reserve(req, 5)
    assert store.reserve_nonce(44005, executor, 3, req.request_id) == 3
    restarted = PostgresPaymentStore(DATABASE_URL, store.cipher._signing_key and store.cipher._encryption_key)
    assert restarted.reserve_nonce(44005, executor, 3, req.request_id) == 3


def test_clear_signed_transaction_preserves_nonce_audit_record():
    key = Fernet.generate_key()
    store = PostgresPaymentStore(DATABASE_URL, key)
    store.reset_for_test()
    req = payment("0x" + "33" * 32)
    executor = "0x000000000000000000000000000000000000aE03"
    store.reserve(req, 7)
    nonce = store.reserve_nonce(44005, executor, 8, req.request_id)
    store.set_signed_transaction(req.request_id, "0x" + "cd" * 32, b"raw", 44005, executor, nonce)
    store.clear_signed_transaction(req.request_id)

    record = store.get(req.request_id)
    assert record["raw_transaction"] is None
    assert record["status"] == "SIGNED_AWAITING_CONSUME"
    assert store.get_nonce_reservation(req.request_id)["nonce"] == nonce
