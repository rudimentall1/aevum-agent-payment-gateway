# AevumPay Gateway

## Status

The Gateway is a fail-closed FastAPI service that prepares an exact EIP-712 payer envelope, verifies the agent's Ed25519 ActionIntent authorization through Verigate, and submits the matching Aevum router transaction. SQLite remains the default ledger. Setting `AEVUMPAY_DATABASE_URL` selects the opt-in PostgreSQL payment ledger, including durable nonce reservations, encrypted signed-transaction persistence and consume-marker state transitions. PostgreSQL nonce reservations are concurrency-tested; full multi-process execution and crash/recovery behavior are not yet acceptance-tested.

The gateway has not yet been integration-tested against a live Verigate instance or Aevum RPC. The router is merged and its Solidity CI is green; live deployment is still pending.

## Configuration

Set these environment variables in the runtime environment. Do not commit secrets.

| Variable | Required | Purpose |
|---|---:|---|
| `AEVUMPAY_ROUTER_ADDRESS` | Yes | Deployed AevumPayPolicyRouter address |
| `AEVUMPAY_EXECUTOR_PRIVATE_KEY` | Yes | EVM executor key; must match router.executor() |
| `AEVUMPAY_API_KEY` | Yes | API key required by gateway payment routes |
| `VERIGATE_URL` | Yes | Base URL of the actual self-hosted Verigate API |
| `VERIGATE_API_KEY` | Yes | Verigate API key |
| `VERIGATE_PUBLIC_KEY_PATH` | Yes | Pinned issuer Ed25519 public-key PEM |
| `VERIGATE_TENANT` | If tenant mode | Exact tenant ID configured on Verigate |
| `AEVUMPAY_RPC_URL` | No | Defaults to QDay Aevum Testnet RPC |
| `AEVUMPAY_TOKEN` | No | Defaults to the documented tUSD8 test token |
| `AEVUMPAY_TOKEN_DECIMALS` | No | Defaults to 6 |
| `AEVUMPAY_CHAIN_ID` | No | Defaults to 44005 |
| `AEVUMPAY_DB` | No | SQLite path; defaults to `data/aevumpay-gateway.db` |
| `AEVUMPAY_DATABASE_URL` | No | PostgreSQL connection URL; when set, selects the shared PostgreSQL payment ledger instead of SQLite |\n| `AEVUMPAY_TX_ENCRYPTION_KEY` | Required for payments | Fernet key used to encrypt persisted signed transaction bytes in either ledger |

The issuer public key must be provisioned out-of-band and pinned at `VERIGATE_PUBLIC_KEY_PATH`. Do not fetch and trust a new issuer key for every payment. When PostgreSQL is enabled, also set `AEVUMPAY_TX_ENCRYPTION_KEY` to a Fernet key; the same key must remain stable across Gateway restarts.

## Run locally

```bash
python -m venv .venv
. .venv/bin/activate
pip install -r gateway/requirements.txt
uvicorn gateway.app:app --host 127.0.0.1 --port 8080
```

Health check: `GET /health`.

## Payment protocol

1. Client calls `POST /v1/payments/typed-data` and signs the returned EIP-712 data with the payer wallet.
2. Client calls `POST /v1/payments/prepare` with the payer signature; it returns the canonical ActionIntent payload.
3. Client signs that payload with the Ed25519 key corresponding to the registered Verigate identity.
4. Client submits both signatures to `POST /v1/payments/execute`.
5. Gateway obtains Verigate ALLOW, verifies the pinned execution authorization, performs on-chain preflight, signs and durably stores the exact transaction bytes.
6. Gateway consumes the exact authorization through Verigate. Only `execute=true` permits broadcast.
7. Gateway broadcasts the stored bytes and verifies the receipt plus exact Transfer and PaymentExecuted events.

The payer must have approved the router to spend the required tUSD8 amount before execution. The gateway checks balance and allowance but does not create an approval transaction.

## Operational safety

- The gateway derives calldata; callers cannot submit arbitrary calldata.
- Decimal amounts are strings and converted exactly to token base units.
- Verigate issuer signatures are verified locally against the pinned Ed25519 public key.
- No EVM transaction is submitted unless Verigate returns ALLOW, the execution authorization verifies, and consume returns `execute=true`.
- Duplicate request IDs are rejected by the selected ledger: SQLite by default, or PostgreSQL when `AEVUMPAY_DATABASE_URL` is configured.
- PostgreSQL mode reserves executor nonces in the shared ledger and atomically persists the encrypted signed transaction with its nonce reservation before Verigate consume. Keep PostgreSQL mode experimental; do not enable multiple workers or replicas until cross-process crash/restart and reconciliation tests pass.
- A timeout after Verigate consumption is an ambiguous state. The gateway preserves a transaction hash when one can be derived or broadcast. Never blindly retry; inspect the ledger and chain first.
- A consumed Verigate authorization is single-use. If broadcast fails, a fresh authorization/request ID is required after reconciliation.
- The gateway currently assumes the Aevum testnet router and tUSD8 configuration. It is not production-ready until live RPC, Verigate, deployment and end-to-end tests pass.


## Docker Compose

The repository includes a container image and a Compose service. The container runs as an unprivileged user, keeps its SQLite ledger in a named volume, and binds the HTTP port to localhost. Signed raw transactions are encrypted in SQLite with Fernet using the separate `AEVUMPAY_TX_ENCRYPTION_KEY`; generate a key with `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"` and keep it outside source control. A database-only leak must not expose immediately broadcastable signed transactions.

```bash
cp .env.example .env
mkdir -p secrets
# Place the pinned Verigate issuer public-key PEM at secrets/verigate-issuer.pub.
# Fill .env locally; never commit it.
docker compose build
docker compose up -d
docker compose ps
curl http://127.0.0.1:8080/health
```

Payment routes remain unavailable until the required runtime values are configured. Do not expose port 8080 directly to the public internet without a TLS reverse proxy and additional operational controls.
