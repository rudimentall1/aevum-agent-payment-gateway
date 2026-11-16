# AevumPay Gateway

## Status

Initial gateway implementation is present. It is a fail-closed FastAPI service that prepares an exact EIP-712 payer envelope, obtains the agent's Ed25519 ActionIntent signature, calls Verigate authorize and consume, then submits the matching Aevum router transaction.

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
| `AEVUMPAY_DB` | No | Defaults to `data/aevumpay-gateway.db` |

The issuer public key must be provisioned out-of-band and pinned at `VERIGATE_PUBLIC_KEY_PATH`. Do not fetch and trust a new issuer key for every payment.

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
4. Gateway authorizes and consumes the exact action through Verigate.
5. Gateway submits the same router calldata to Aevum and records the receipt.

The payer must have approved the router to spend the required tUSD8 amount before execution. The gateway checks balance and allowance but does not create an approval transaction.

## Operational safety

- The gateway derives calldata; callers cannot submit arbitrary calldata.
- Decimal amounts are strings and converted exactly to token base units.
- Verigate issuer signatures are verified locally against the pinned Ed25519 public key.
- No EVM transaction is submitted unless Verigate returns ALLOW, the execution authorization verifies, and consume returns `execute=true`.
- Duplicate request IDs are rejected using a local SQLite ledger.
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
