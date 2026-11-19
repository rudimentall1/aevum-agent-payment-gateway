# AevumPay

**Policy-Controlled Payments for AI Agents on QDay Aevum**

AevumPay is a non-custodial payment gateway for AI agents. It combines an external authorization decision from Verigate with deterministic on-chain payment constraints enforced by an Aevum smart contract.

## Why

Agents need to make payments without receiving unrestricted wallet authority. AevumPay constrains each payment by token, recipient, exact amount, expiry and one-time request identifier. The agent cannot use the router to redirect or enlarge an approved payment.

## Execution flow

1. The payer requests EIP-712 typed data from the gateway for a specific payer, token, recipient, amount, request ID, deadline, chain and router.
2. The payer signs that typed data and approves the router to spend the exact tUSD8 amount.
3. The gateway prepares the canonical Verigate ActionIntent and exact router calldata. The agent signs the canonical ActionIntent payload; the payer signature is already bound into the calldata.
4. The gateway verifies both signatures, checks the Aevum chain/router/token state, balance, allowance and gas, signs the exact EVM transaction, and persists its encrypted raw bytes before consuming one-time authority.
5. The gateway requests executable authorization from Verigate, verifies the pinned Ed25519 issuer signature and exact action binding, then calls Verigate consume. It proceeds only when consume returns `execute=true`.
6. After recording successful consumption, the gateway broadcasts the exact previously signed transaction bytes. It does not rebuild calldata, nonce or gas after consume.
7. The gateway marks a payment CONFIRMED only after a successful receipt contains both the expected ERC-20 Transfer and AevumPay PaymentExecuted events. Ambiguous outcomes remain reconcilable by re-broadcasting only the identical signed bytes.

Verigate is an existing external service dependency, not new AevumPay contest implementation. The on-chain router does not claim to verify Verigate's Ed25519 signature. It independently verifies the payer's EIP-712 payment signature and enforces payment constraints.

## Network

QDay Aevum Testnet, chain ID 44005 (0xabe5). Test token tUSD8: `0x456569838f1d43009A91ebA4263147Afd7233483`, 6 decimals. See [network configuration](docs/NETWORK_CONFIG.md).

## Current status

- EIP-712 policy router, deployment script, threat model and 15 Foundry tests are implemented.
- FastAPI gateway exposes typed-data, prepare, execute, status and reconciliation endpoints.
- PostgreSQL payment ledger is integrated as an explicit opt-in runtime backend through `AEVUMPAY_DATABASE_URL`; SQLite remains the default.
- PostgreSQL uses durable nonce reservations, encrypted signed-transaction storage and a durable Verigate-consumed marker. A definitively rejected, unconsumed payment can release its nonce for safe reuse while preserving an audit row. Ambiguous consume outcomes retain the reservation and signed bytes for manual reconciliation.
- Gateway CI runs unit and PostgreSQL integration tests and builds the Docker image. Solidity CI compiles the router and runs Foundry tests.
- Latest verified pre-fix main commit `a7fc4b25e85bcb1ffda86a3ebe0ad1cfc6560a59`: Gateway CI and Solidity CI passed (45 Gateway tests; Docker build successful).
- A regression test then exposed a PostgreSQL nonce-gap bug after safe Verigate rejection. The fix and its full CI verification are in progress; check the latest Actions status before treating current main as green.
- The router has not been deployed to Aevum. No AevumPay testnet payment has been sent. The gateway has not been live-integrated with Verigate.

See [network configuration](docs/NETWORK_CONFIG.md), [gateway setup](gateway/README.md), and [session checkpoint](SESSION-CHECKPOINT.md) for exact evidence and remaining external requirements.

## Scope and safety

- EOA is the primary execution path.
- ERC-4337/session keys are optional and will only be claimed after a reproducible Aevum UserOperation.
- No custodial escrow.
- No float-based token amounts.
- Fail closed when authorization, signature verification, consume, or chain checks fail.
- The gateway currently requires one Uvicorn worker and one running replica. An in-process execution lock serializes nonce lookup/signing through broadcast; horizontal scaling requires a shared, durable nonce reservation mechanism.
- Never store private keys, API keys or tenant credentials in the repository.

## Development

See [architecture](docs/ARCHITECTURE.md), [API reference](docs/API.md), [acceptance criteria](docs/ACCEPTANCE_CRITERIA.md), and [build plan](docs/BUILD_PLAN.md).
