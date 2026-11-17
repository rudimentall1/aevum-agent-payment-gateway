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

- EIP-712 policy router, deployment script, threat model and 15 Foundry tests are implemented. GitHub Actions compiled the contract and passed all 15 tests.
- FastAPI gateway is implemented with typed-data, prepare, execute, status and reconciliation endpoints.
- Gateway CI passed its unit-test suite and Docker image build on commit `3d38cfa2c186846d20e69890bf24cfafdcc016ba` (run [43856166920](https://github.com/rudimentall1/aevum-agent-payment-gateway/actions/runs/43856166920)).
- Gateway CI passed all 27 tests and built the Docker image after executor nonce serialization (run [44037402225](https://github.com/rudimentall1/aevum-agent-payment-gateway/actions/runs/44037402225)).
- Gateway CI passed all 29 tests and built the Docker image after crash-recovery regression coverage (run [44048575495](https://github.com/rudimentall1/aevum-agent-payment-gateway/actions/runs/44048575495)).
- Solidity CI passed on the same commit (run [44048575476](https://github.com/rudimentall1/aevum-agent-payment-gateway/actions/runs/44048575476)).
- Solidity CI passed on the same code commit (run [44037402131](https://github.com/rudimentall1/aevum-agent-payment-gateway/actions/runs/44037402131)).
- These CI results are tied to their recorded commits/runs; they are not a claim that the latest documentation-only HEAD has been re-run.
- The router has not been deployed to Aevum. No AevumPay testnet payment has been sent. The gateway has not been live-integrated with Verigate.

See [session checkpoint](SESSION-CHECKPOINT.md) for evidence status and next steps.

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
