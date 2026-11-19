import multiprocessing
import os
from types import SimpleNamespace

import pytest
import psycopg
from fastapi import HTTPException
from cryptography.fernet import Fernet

from gateway.postgres_ledger import PostgresPaymentStore


DATABASE_URL = os.getenv("AEVUMPAY_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="PostgreSQL integration URL is not configured")


def reset_ledger_tables():
    with psycopg.connect(DATABASE_URL) as db:
        db.execute("TRUNCATE aevumpay_payment_nonce_reservations, aevumpay_payments CASCADE")


def payment(request_id="0x" + "11" * 32):
    return SimpleNamespace(
        request_id=request_id,
        intent_id="intent-1",
        payer="0x0000000000000000000000000000000000000001",
        recipient="0x0000000000000000000000000000000000000002",
    )


def test_payment_record_is_durable_and_duplicate_request_is_rejected():
    key = Fernet.generate_key()
    store = PostgresPaymentStore(DATABASE_URL, key)
    reset_ledger_tables()
    req = payment()
    store.reserve(req, 1_250_000)

    restarted = PostgresPaymentStore(DATABASE_URL, key)
    record = restarted.get(req.request_id)
    assert record["status"] == "AUTHORIZING"
    assert record["amount_base_units"] == "1250000"

    with pytest.raises(HTTPException) as exc:
        store.reserve(req, 1_250_000)
    assert exc.value.status_code == 409


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
    key = Fernet.generate_key()
    store = PostgresPaymentStore(DATABASE_URL, key)
    store.reset_for_test()
    executor = "0x000000000000000000000000000000000000aE02"
    with pytest.raises(ValueError, match="payment"):
        store.reserve_nonce(44005, executor, 3, "missing-payment")

    req = payment("0x" + "22" * 32)
    store.reserve(req, 5)
    assert store.reserve_nonce(44005, executor, 3, req.request_id) == 3
    restarted = PostgresPaymentStore(DATABASE_URL, key)
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


def _reserve_ledger_nonce_worker(database_url, key, request_id, executor, barrier, queue):
    store = PostgresPaymentStore(database_url, key)
    barrier.wait(timeout=15)
    try:
        nonce = store.reserve_nonce(44005, executor, 31, request_id)
        queue.put(("ok", nonce))
    except Exception as exc:
        queue.put(("error", type(exc).__name__))


def test_independent_processes_reserve_distinct_nonces_for_different_payments():
    key = Fernet.generate_key()
    store = PostgresPaymentStore(DATABASE_URL, key)
    store.reset_for_test()
    workers = 5
    executor = "0x000000000000000000000000000000000000aE04"
    request_ids = ["0x" + f"{i:02x}" * 32 for i in range(40, 40 + workers)]
    for request_id in request_ids:
        store.reserve(payment(request_id), 1)
    ctx = multiprocessing.get_context("spawn")
    barrier = ctx.Barrier(workers)
    queue = ctx.Queue()
    processes = [
        ctx.Process(
            target=_reserve_ledger_nonce_worker,
            args=(DATABASE_URL, key, request_id, executor, barrier, queue),
        )
        for request_id in request_ids
    ]
    for process in processes:
        process.start()
    results = [queue.get(timeout=30) for _ in processes]
    for process in processes:
        process.join(timeout=30)
        assert process.exitcode == 0
    assert all(result[0] == "ok" for result in results), results
    assert sorted(result[1] for result in results) == list(range(31, 31 + workers))


def test_consume_marker_cannot_be_written_without_durable_signed_transaction():
    store = PostgresPaymentStore(DATABASE_URL, Fernet.generate_key())
    store.reset_for_test()
    req = payment("0x" + "44" * 32)
    store.reserve(req, 1)
    with pytest.raises(ValueError, match="signed transaction"):
        store.update(req.request_id, "AUTHORIZED_CONSUMED")
    record = store.get(req.request_id)
    assert record["authorization_consumed"] is False
    assert record["status"] == "AUTHORIZING"
