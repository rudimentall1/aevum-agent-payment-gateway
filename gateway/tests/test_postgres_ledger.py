import multiprocessing
import os
from types import SimpleNamespace

import pytest
import psycopg
from fastapi import HTTPException
from cryptography.fernet import Fernet
from web3 import Web3 as RealWeb3

import gateway.app as gateway_app

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
    reset_ledger_tables()
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
    reset_ledger_tables()
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
    reset_ledger_tables()
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
    reset_ledger_tables()
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
    reset_ledger_tables()
    req = payment("0x" + "44" * 32)
    store.reserve(req, 1)
    with pytest.raises(ValueError, match="signed transaction"):
        store.update(req.request_id, "AUTHORIZED_CONSUMED")
    record = store.get(req.request_id)
    assert record["authorization_consumed"] is False
    assert record["status"] == "AUTHORIZING"


def test_postgres_reconcile_refuses_broadcast_until_consume_marker_is_durable(monkeypatch):
    key = Fernet.generate_key()
    store = PostgresPaymentStore(DATABASE_URL, key)
    reset_ledger_tables()
    req = payment("0x" + "55" * 32)
    executor = "0x000000000000000000000000000000000000aE05"
    store.reserve(req, 123)
    nonce = store.reserve_nonce(44005, executor, 22, req.request_id)
    raw = b"postgres-signed-transaction"
    tx_hash = RealWeb3.keccak(raw).hex()
    store.set_signed_transaction(req.request_id, tx_hash, raw, 44005, executor, nonce)
    monkeypatch.setattr(gateway_app, "store", store)

    rpc_attempts = []

    class ForbiddenRpc:
        def __init__(self, *_args, **_kwargs):
            rpc_attempts.append(True)

    monkeypatch.setattr(gateway_app, "Web3", ForbiddenRpc)
    with pytest.raises(gateway_app.HTTPException) as exc:
        gateway_app.reconcile_payment(req.request_id)

    assert exc.value.status_code == 409
    assert rpc_attempts == []
    assert store.get(req.request_id)["authorization_consumed"] is False


def test_postgres_reconcile_after_store_restart_broadcasts_identical_signed_bytes(monkeypatch):
    key = Fernet.generate_key()
    store = PostgresPaymentStore(DATABASE_URL, key)
    reset_ledger_tables()
    req = payment("0x" + "66" * 32)
    executor = "0x000000000000000000000000000000000000aE06"
    store.reserve(req, 456)
    nonce = store.reserve_nonce(44005, executor, 28, req.request_id)
    raw = b"postgres-exact-signed-transaction"
    tx_hash = RealWeb3.keccak(raw).hex()
    store.set_signed_transaction(req.request_id, tx_hash, raw, 44005, executor, nonce)
    store.update(req.request_id, "AUTHORIZED_CONSUMED")

    restarted = PostgresPaymentStore(DATABASE_URL, key)
    monkeypatch.setattr(gateway_app, "store", restarted)
    broadcasts = []

    class FakeEth:
        chain_id = gateway_app.CHAIN_ID

        def send_raw_transaction(self, transaction):
            broadcasts.append(bytes(transaction))
            return type("TxHash", (), {"hex": lambda self: tx_hash})()

        def wait_for_transaction_receipt(self, _tx_hash, timeout):
            assert timeout >= 60
            return SimpleNamespace(status=1, logs=[])

    fake_eth = FakeEth()

    class FakeWeb3:
        def __init__(self, *_args, **_kwargs):
            self.eth = fake_eth

        def is_connected(self):
            return True

        @staticmethod
        def HTTPProvider(*_args, **_kwargs):
            return object()

        @staticmethod
        def keccak(value):
            return RealWeb3.keccak(value)

        @staticmethod
        def to_bytes(hexstr):
            return bytes.fromhex(hexstr[2:])

    monkeypatch.setattr(gateway_app, "Web3", FakeWeb3)
    monkeypatch.setattr(gateway_app, "verify_payment_events", lambda *_args: True)

    result = gateway_app.reconcile_payment(req.request_id)

    assert broadcasts == [raw]
    assert result["status"] == "CONFIRMED"
    assert result["tx_hash"] == tx_hash
    assert restarted.get(req.request_id)["authorization_consumed"] is True
    assert restarted.get(req.request_id)["raw_transaction"] is None
    assert restarted.get_nonce_reservation(req.request_id)["state"] == "CONFIRMED"


def test_rejected_unconsumed_payment_releases_nonce_for_reuse_without_overwriting_audit():
    key = Fernet.generate_key()
    store = PostgresPaymentStore(DATABASE_URL, key)
    reset_ledger_tables()
    executor = "0x000000000000000000000000000000000000aE07"

    rejected = payment("0x" + "77" * 32)
    later = payment("0x" + "88" * 32)
    retry = payment("0x" + "99" * 32)
    for req in (rejected, later, retry):
        store.reserve(req, 10)

    rejected_nonce = store.reserve_nonce(44005, executor, 17, rejected.request_id)
    later_nonce = store.reserve_nonce(44005, executor, 17, later.request_id)
    assert (rejected_nonce, later_nonce) == (17, 18)

    store.set_signed_transaction(
        rejected.request_id, "0x" + "ab" * 32, b"rejected-signed-bytes",
        44005, executor, rejected_nonce,
    )
    store.update(rejected.request_id, "REJECTED", detail="Verigate denied before consume")
    store.release_nonce_reservation(rejected.request_id)
    store.clear_signed_transaction(rejected.request_id)

    retry_nonce = store.reserve_nonce(44005, executor, 17, retry.request_id)
    assert retry_nonce == 17
    assert store.get_nonce_reservation(rejected.request_id)["state"] == "ABANDONED"
    assert store.get_nonce_reservation(later.request_id)["nonce"] == 18


def test_consumed_nonce_reservation_cannot_be_released():
    key = Fernet.generate_key()
    store = PostgresPaymentStore(DATABASE_URL, key)
    reset_ledger_tables()
    req = payment("0x" + "aa" * 32)
    executor = "0x000000000000000000000000000000000000aE08"
    store.reserve(req, 10)
    nonce = store.reserve_nonce(44005, executor, 23, req.request_id)
    store.set_signed_transaction(
        req.request_id, "0x" + "cd" * 32, b"consumed-signed-bytes",
        44005, executor, nonce,
    )
    store.update(req.request_id, "AUTHORIZED_CONSUMED")

    with pytest.raises(ValueError, match="consumed"):
        store.release_nonce_reservation(req.request_id)
