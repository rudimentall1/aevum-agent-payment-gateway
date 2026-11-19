from __future__ import annotations

import hashlib
import re
import time
from typing import Any

import psycopg
from cryptography.fernet import Fernet
from fastapi import HTTPException
from psycopg.rows import dict_row


_ADDRESS_RE = re.compile(r"^0x[0-9a-fA-F]{40}$")


class PostgresPaymentStore:
    """Shared durable payment ledger and nonce reservations.

    Each state transition that affects payment execution and its nonce audit
    record is committed in one PostgreSQL transaction. This adapter is not
    wired into the HTTP execution path yet.
    """

    def __init__(self, database_url: str, encryption_key: str | bytes):
        if not database_url:
            raise ValueError("PostgreSQL database URL is required")
        if not encryption_key:
            raise ValueError("transaction encryption key is required")
        key = encryption_key.encode() if isinstance(encryption_key, str) else encryption_key
        self.cipher = Fernet(key)
        self.database_url = database_url
        self.initialize()

    def _connect(self):
        return psycopg.connect(self.database_url, row_factory=dict_row, connect_timeout=5)

    def initialize(self) -> None:
        with self._connect() as db:
            db.execute("""
                CREATE TABLE IF NOT EXISTS aevumpay_payments (
                    request_id TEXT PRIMARY KEY,
                    intent_id TEXT NOT NULL,
                    payer TEXT NOT NULL,
                    recipient TEXT NOT NULL,
                    amount_base_units TEXT NOT NULL,
                    status TEXT NOT NULL,
                    tx_hash TEXT,
                    raw_transaction BYTEA,
                    authorization_consumed BOOLEAN NOT NULL DEFAULT FALSE,
                    detail TEXT,
                    created_at BIGINT NOT NULL,
                    updated_at BIGINT NOT NULL
                )
            """)
            db.execute("""
                CREATE TABLE IF NOT EXISTS aevumpay_payment_nonce_reservations (
                    chain_id BIGINT NOT NULL,
                    executor_address TEXT NOT NULL,
                    nonce BIGINT NOT NULL CHECK (nonce >= 0),
                    request_id TEXT NOT NULL UNIQUE REFERENCES aevumpay_payments(request_id),
                    state TEXT NOT NULL DEFAULT 'RESERVED',
                    tx_hash TEXT,
                    created_at BIGINT NOT NULL,
                    updated_at BIGINT NOT NULL,
                    PRIMARY KEY (chain_id, executor_address, nonce)
                )
            """)

    @staticmethod
    def _lock_key(chain_id: int, executor_address: str) -> int:
        digest = hashlib.sha256(
            f"{chain_id}:{executor_address.lower()}".encode("ascii")
        ).digest()
        return int.from_bytes(digest[:8], "big", signed=True)

    def reserve(self, req: Any, amount_units: int) -> None:
        now = int(time.time())
        try:
            with self._connect() as db:
                db.execute(
                    """INSERT INTO aevumpay_payments
                       (request_id, intent_id, payer, recipient, amount_base_units,
                        status, created_at, updated_at)
                       VALUES (%s, %s, %s, %s, %s, 'AUTHORIZING', %s, %s)""",
                    (req.request_id.lower(), req.intent_id, req.payer.lower(),
                     req.recipient.lower(), str(amount_units), now, now),
                )
        except psycopg.errors.UniqueViolation as exc:
            raise HTTPException(
                status_code=409,
                detail="request_id already exists; inspect payment status",
            ) from exc

    def reserve_nonce(
        self, chain_id: int, executor_address: str, pending_nonce: int, request_id: str
    ) -> int:
        if chain_id <= 0 or pending_nonce < 0:
            raise ValueError("chain_id must be positive and pending_nonce non-negative")
        if not _ADDRESS_RE.fullmatch(executor_address):
            raise ValueError("executor_address must be a 20-byte EVM address")
        if not request_id or len(request_id) > 200:
            raise ValueError("request_id must contain 1 to 200 characters")
        executor = executor_address.lower()
        now = int(time.time())
        with self._connect() as db:
            db.execute("SELECT pg_advisory_xact_lock(%s)", (self._lock_key(chain_id, executor),))
            payment = db.execute(
                "SELECT request_id FROM aevumpay_payments WHERE request_id=%s",
                (request_id.lower(),),
            ).fetchone()
            if payment is None:
                raise ValueError("payment must exist before reserving its nonce")
            existing = db.execute(
                """SELECT chain_id, executor_address, nonce
                   FROM aevumpay_payment_nonce_reservations WHERE request_id=%s""",
                (request_id.lower(),),
            ).fetchone()
            if existing:
                if existing["chain_id"] != chain_id or existing["executor_address"] != executor:
                    raise ValueError("request_id already has a reservation for another executor")
                return existing["nonce"]
            highest = db.execute(
                """SELECT MAX(nonce) AS nonce FROM aevumpay_payment_nonce_reservations
                   WHERE chain_id=%s AND executor_address=%s""",
                (chain_id, executor),
            ).fetchone()["nonce"]
            nonce = max(pending_nonce, highest + 1 if highest is not None else pending_nonce)
            db.execute(
                """INSERT INTO aevumpay_payment_nonce_reservations
                   (chain_id, executor_address, nonce, request_id, created_at, updated_at)
                   VALUES (%s, %s, %s, %s, %s, %s)""",
                (chain_id, executor, nonce, request_id.lower(), now, now),
            )
            return nonce

    def set_signed_transaction(
        self, request_id: str, tx_hash: str, raw_transaction: bytes,
        chain_id: int, executor_address: str, nonce: int,
    ) -> None:
        encrypted = self.cipher.encrypt(raw_transaction)
        now = int(time.time())
        with self._connect() as db:
            payment = db.execute(
                """UPDATE aevumpay_payments SET status='SIGNED_AWAITING_CONSUME',
                   tx_hash=%s, raw_transaction=%s, updated_at=%s
                   WHERE request_id=%s RETURNING request_id""",
                (tx_hash, encrypted, now, request_id.lower()),
            ).fetchone()
            if payment is None:
                raise ValueError("payment does not exist")
            reservation = db.execute(
                """UPDATE aevumpay_payment_nonce_reservations
                   SET state='SIGNED', tx_hash=%s, updated_at=%s
                   WHERE request_id=%s AND chain_id=%s AND executor_address=%s AND nonce=%s
                   RETURNING request_id""",
                (tx_hash, now, request_id.lower(), chain_id, executor_address.lower(), nonce),
            ).fetchone()
            if reservation is None:
                raise ValueError("matching nonce reservation does not exist")

    def update(
        self, request_id: str, status: str,
        tx_hash: str | None = None, detail: str | None = None,
    ) -> None:
        now = int(time.time())
        normalized_id = request_id.lower()
        with self._connect() as db:
            if status == "AUTHORIZED_CONSUMED":
                payment = db.execute(
                    """SELECT raw_transaction FROM aevumpay_payments
                       WHERE request_id=%s FOR UPDATE""",
                    (normalized_id,),
                ).fetchone()
                if payment is None:
                    raise ValueError("payment does not exist")
                if payment["raw_transaction"] is None:
                    raise ValueError("cannot consume authorization before signed transaction is durable")
                reservation = db.execute(
                    """SELECT state FROM aevumpay_payment_nonce_reservations
                       WHERE request_id=%s FOR UPDATE""",
                    (normalized_id,),
                ).fetchone()
                if reservation is None or reservation["state"] != "SIGNED":
                    raise ValueError("signed nonce reservation is not durable")
                db.execute(
                    """UPDATE aevumpay_payments SET status=%s,
                       tx_hash=COALESCE(%s, tx_hash), detail=%s,
                       authorization_consumed=TRUE, updated_at=%s
                       WHERE request_id=%s""",
                    (status, tx_hash, detail, now, normalized_id),
                )
                db.execute(
                    """UPDATE aevumpay_payment_nonce_reservations
                       SET state=%s, tx_hash=COALESCE(%s, tx_hash), updated_at=%s
                       WHERE request_id=%s""",
                    (status, tx_hash, now, normalized_id),
                )
                return

            updated = db.execute(
                """UPDATE aevumpay_payments SET status=%s,
                   tx_hash=COALESCE(%s, tx_hash), detail=%s, updated_at=%s
                   WHERE request_id=%s RETURNING request_id""",
                (status, tx_hash, detail, now, normalized_id),
            ).fetchone()
            if updated is None:
                raise ValueError("payment does not exist")
            db.execute(
                """UPDATE aevumpay_payment_nonce_reservations
                   SET state=%s, tx_hash=COALESCE(%s, tx_hash), updated_at=%s
                   WHERE request_id=%s""",
                (status, tx_hash, now, normalized_id),
            )

    def clear_signed_transaction(self, request_id: str) -> None:
        with self._connect() as db:
            db.execute(
                """UPDATE aevumpay_payments SET raw_transaction=NULL, updated_at=%s
                   WHERE request_id=%s""",
                (int(time.time()), request_id.lower()),
            )

    def get(self, request_id: str) -> dict[str, Any] | None:
        with self._connect() as db:
            row = db.execute(
                "SELECT * FROM aevumpay_payments WHERE request_id=%s",
                (request_id.lower(),),
            ).fetchone()
            return dict(row) if row else None

    def get_nonce_reservation(self, request_id: str) -> dict[str, Any] | None:
        with self._connect() as db:
            row = db.execute(
                """SELECT * FROM aevumpay_payment_nonce_reservations
                   WHERE request_id=%s""",
                (request_id.lower(),),
            ).fetchone()
            return dict(row) if row else None

    def reset_for_test(self) -> None:
        """Test helper; use only with a dedicated disposable database."""
        with self._connect() as db:
            db.execute("TRUNCATE aevumpay_payment_nonce_reservations, aevumpay_payments CASCADE")
