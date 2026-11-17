from __future__ import annotations

import hashlib
import re
from contextlib import closing

import psycopg
from psycopg.rows import dict_row


_ADDRESS_RE = re.compile(r"^0x[0-9a-fA-F]{40}$")


class PostgresNonceStore:
    """Durable nonce reservations shared by independent Gateway processes.

    This is intentionally a narrow primitive. It is not wired into payment
    execution until the complete PostgreSQL payment ledger is implemented.
    """

    def __init__(self, database_url: str):
        if not database_url:
            raise ValueError("PostgreSQL database URL is required")
        self.database_url = database_url
        self.initialize()

    def _connect(self):
        return psycopg.connect(self.database_url, row_factory=dict_row, connect_timeout=5)

    def initialize(self) -> None:
        with self._connect() as db:
            db.execute("""
                CREATE TABLE IF NOT EXISTS aevumpay_nonce_reservations (
                    chain_id BIGINT NOT NULL,
                    executor_address TEXT NOT NULL,
                    nonce BIGINT NOT NULL CHECK (nonce >= 0),
                    request_id TEXT NOT NULL UNIQUE,
                    state TEXT NOT NULL DEFAULT 'RESERVED',
                    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                    PRIMARY KEY (chain_id, executor_address, nonce)
                )
            """)

    @staticmethod
    def _lock_key(chain_id: int, executor_address: str) -> int:
        digest = hashlib.sha256(
            f"{chain_id}:{executor_address.lower()}".encode("ascii")
        ).digest()
        return int.from_bytes(digest[:8], "big", signed=True)

    def reserve_nonce(
        self,
        chain_id: int,
        executor_address: str,
        pending_nonce: int,
        request_id: str,
    ) -> int:
        if chain_id <= 0 or pending_nonce < 0:
            raise ValueError("chain_id must be positive and pending_nonce non-negative")
        if not _ADDRESS_RE.fullmatch(executor_address):
            raise ValueError("executor_address must be a 20-byte EVM address")
        if not request_id or len(request_id) > 200:
            raise ValueError("request_id must contain 1 to 200 characters")

        executor = executor_address.lower()
        with self._connect() as db:
            # Transaction-scoped lock serializes nonce selection for this
            # executor. The unique primary key remains the final race guard.
            db.execute(
                "SELECT pg_advisory_xact_lock(%s)",
                (self._lock_key(chain_id, executor),),
            )
            existing = db.execute(
                """SELECT nonce FROM aevumpay_nonce_reservations
                   WHERE request_id=%s""",
                (request_id,),
            ).fetchone()
            if existing:
                raise ValueError("request_id already has a nonce reservation")

            highest = db.execute(
                """SELECT MAX(nonce) AS nonce FROM aevumpay_nonce_reservations
                   WHERE chain_id=%s AND executor_address=%s""",
                (chain_id, executor),
            ).fetchone()["nonce"]
            nonce = max(pending_nonce, highest + 1 if highest is not None else pending_nonce)
            db.execute(
                """INSERT INTO aevumpay_nonce_reservations
                   (chain_id, executor_address, nonce, request_id)
                   VALUES (%s, %s, %s, %s)""",
                (chain_id, executor, nonce, request_id),
            )
            return nonce

    def reset_for_test(self) -> None:
        """Clear reservations. Never call from application runtime."""
        with self._connect() as db:
            db.execute("TRUNCATE TABLE aevumpay_nonce_reservations")
