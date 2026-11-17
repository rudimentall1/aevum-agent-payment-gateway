import multiprocessing
import os
import time

import pytest

from gateway.postgres_nonce import PostgresNonceStore


DATABASE_URL = os.getenv("AEVUMPAY_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="PostgreSQL integration URL is not configured")


def _reserve_worker(database_url, chain_id, executor, pending_nonce, request_id, barrier, queue):
    store = PostgresNonceStore(database_url)
    barrier.wait(timeout=15)
    try:
        nonce = store.reserve_nonce(
            chain_id=chain_id,
            executor_address=executor,
            pending_nonce=pending_nonce,
            request_id=request_id,
        )
        queue.put(("ok", nonce))
    except Exception as exc:
        queue.put(("error", type(exc).__name__))


def test_independent_processes_reserve_distinct_sequential_nonces():
    store = PostgresNonceStore(DATABASE_URL)
    store.reset_for_test()
    ctx = multiprocessing.get_context("spawn")
    workers = 6
    barrier = ctx.Barrier(workers)
    queue = ctx.Queue()
    executor = "0x000000000000000000000000000000000000aE01"
    processes = [
        ctx.Process(
            target=_reserve_worker,
            args=(DATABASE_URL, 44005, executor, 41, f"request-{i}", barrier, queue),
        )
        for i in range(workers)
    ]
    for process in processes:
        process.start()
    results = [queue.get(timeout=30) for _ in processes]
    for process in processes:
        process.join(timeout=30)
        assert process.exitcode == 0
    assert all(result[0] == "ok" for result in results), results
    assert sorted(result[1] for result in results) == list(range(41, 41 + workers))


def test_duplicate_request_id_cannot_claim_two_nonces():
    store = PostgresNonceStore(DATABASE_URL)
    store.reset_for_test()
    executor = "0x000000000000000000000000000000000000aE02"
    first = store.reserve_nonce(44005, executor, 7, "same-request")
    with pytest.raises(ValueError, match="already has a nonce"):
        store.reserve_nonce(44005, executor, 7, "same-request")
    assert first == 7


def test_reservation_survives_store_restart_and_is_not_recycled():
    executor = "0x000000000000000000000000000000000000aE03"
    first_store = PostgresNonceStore(DATABASE_URL)
    first_store.reset_for_test()
    assert first_store.reserve_nonce(44005, executor, 12, "crashed-request") == 12

    restarted_store = PostgresNonceStore(DATABASE_URL)
    assert restarted_store.reserve_nonce(44005, executor, 12, "next-request") == 13
