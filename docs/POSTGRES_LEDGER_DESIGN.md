# PostgreSQL Ledger and Nonce Coordination

Status: partial implementation. The standalone nonce reservation primitive is implemented and CI-tested against PostgreSQL 16. The shared payment ledger, transactional payment-state transitions and execution integration are not implemented. PostgreSQL mode is not production-ready and must not be used to enable multiple Gateway replicas.

## Goal

Allow more than one Gateway process to share payment state without allowing two processes to sign transactions with the same executor nonce. SQLite remains the default single-process backend until the PostgreSQL path is complete and explicitly configured.

## Required invariants

1. Every payment request ID is globally unique across all Gateway replicas.
2. A signed transaction is durably encrypted in the shared ledger before Verigate consume begins.
3. The exact signed bytes are the only bytes eligible for broadcast or reconciliation.
4. A nonce assigned to a signed transaction is never silently released because a process timed out or disappeared.
5. An ambiguous Verigate consume outcome never triggers an automatic broadcast unless the ledger durably records consume success.
6. A nonce reservation is not reusable until the system has authoritative evidence that the transaction was not broadcast and cannot later be broadcast, or that the transaction has reached a terminal on-chain outcome.
7. No replica may enter the executor critical section without holding the shared database coordination primitive.

## Implemented slice: nonce reservation

`gateway/postgres_nonce.py` currently provides an isolated `PostgresNonceStore`:
- PostgreSQL 16 compatible, using psycopg v3.
- Transaction-scoped advisory lock keyed by chain ID and normalized executor address.
- Durable unique constraint on (chain_id, executor_address, nonce).
- Globally unique request ID constraint.
- Conservative allocation from max(pending_nonce, highest_reserved_nonce + 1); abandoned reservations are not silently recycled.
- The primitive is not imported or called by `gateway/app.py` and does not replace the SQLite payment store.

CI uses a real PostgreSQL 16 service. The integration tests spawn six independent processes to reserve nonces concurrently, reject duplicate request IDs, and verify a reservation remains allocated after constructing a new store instance. Verified run: https://github.com/rudimentall1/aevum-agent-payment-gateway/actions/runs/44054246429 (32 Gateway tests passed; Docker image build succeeded).

## Remaining PostgreSQL schema

### payments

Keep the existing payment fields and semantics:

- request_id TEXT PRIMARY KEY
- intent_id, payer, recipient, amount_base_units
- status, tx_hash, encrypted raw_transaction
- authorization_consumed BOOLEAN NOT NULL DEFAULT FALSE
- detail, created_at, updated_at

Use BYTEA for encrypted raw_transaction and TIMESTAMPTZ for timestamps. Keep amount_base_units as TEXT to avoid accidental numeric coercion.

### nonce_reservations

The initial primitive currently has chain_id, executor_address, nonce, request_id, state and timestamps. The complete ledger still needs:
- request_id TEXT NOT NULL UNIQUE REFERENCES payments(request_id)
- tx_hash TEXT
- explicit state transitions for RESERVED, SIGNED, AUTHORIZATION_CONSUMED, BROADCAST, CONFIRMED, REVERTED and MANUAL_REVIEW
- durable association between reservation, payment row and exact signed transaction

The schema must be migrated carefully from the current primitive table without dropping or recycling existing reservations.

## Execution protocol

1. Begin a PostgreSQL transaction and acquire a transaction-scoped advisory lock keyed by chain ID and normalized executor address.
2. Read the chain pending nonce while holding the lock.
3. Select the first nonce not already present in nonce_reservations for this chain and executor, starting at the chain pending nonce.
4. Insert the reservation with a unique constraint. A conflict means retry the reservation transaction; never ignore the conflict.
5. Sign the transaction with the reserved nonce.
6. Persist the encrypted exact raw transaction and its hash in payments, and transition the reservation to SIGNED in one database transaction.
7. Commit the reservation and release the advisory lock before making the Verigate HTTP request. The durable unique reservation prevents another replica from reusing the nonce.
8. After Verigate consume returns execute=true, atomically set payments.authorization_consumed and nonce_reservations.state=AUTHORIZATION_CONSUMED.
9. Broadcast only the persisted signed bytes. Record BROADCAST/PENDING/terminal state as evidence arrives.
10. Reconciliation reads the shared ledger and chain. It may rebroadcast only the same signed bytes and only after durable consume confirmation.

The advisory lock protects nonce selection and reservation. The unique database constraint is the final concurrency guard. The durable reservation, not a long-lived network lock, protects the nonce across process crashes and database connection loss.

## Failure handling

- Crash before reservation: no nonce has been claimed.
- Crash after reservation but before signing: retain the reservation for reconciliation; do not silently reuse it.
- Crash after signing but before Verigate consume: retain encrypted bytes and reservation. No automatic broadcast.
- Crash during consume: retain bytes and reservation; require authoritative consume reconciliation.
- Crash after consume marker but before broadcast: reconciliation may broadcast the exact stored bytes.
- RPC broadcast timeout: retain bytes and reservation; inspect transaction hash/receipt before any retry.
- Confirmed or reverted receipt: mark terminal and retain an audit record. Do not delete the nonce history.

## Migration and rollout

- Add PostgreSQL as an opt-in backend selected by DATABASE_URL; do not silently change existing SQLite deployments.
- Keep SQLite behavior and its process-local lock unchanged.
- Do not enable multiple workers or replicas until the PostgreSQL integration tests pass.
- Do not attempt an automatic SQLite-to-PostgreSQL production migration in this slice. A separate explicit export/import tool can be added only if an existing deployment needs it.

## Acceptance tests

Run against a real PostgreSQL service in CI, not a mocked SQL adapter:

1. Two independent processes reserve nonces concurrently for the same executor; reservations are unique and sequential.
2. Two different executors can reserve concurrently without unnecessary global serialization.
3. Duplicate request IDs are rejected across processes.
4. A process crash after reservation does not make the nonce available to another process.
5. A process crash after consume marker allows a restarted process to load and broadcast the identical encrypted transaction bytes.
6. A crash before consume marker prevents automatic broadcast.
7. Database restart preserves payment rows, encrypted transaction bytes, and nonce reservations.
8. Existing SQLite tests and the full Gateway suite remain green.

## Rollout gate

PostgreSQL mode remains experimental and single-replica until the complete shared payment ledger, transactional state transitions and crash-recovery acceptance tests pass. Multi-replica operation is not enabled by merely adding a PostgreSQL connection string.
