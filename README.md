# AevumPay

**Policy-Controlled Payments for AI Agents on QDay Aevum**

AevumPay is a non-custodial payment gateway for AI agents. It combines an external authorization decision from Verigate with deterministic on-chain payment constraints enforced by an Aevum smart contract.

## Why
Agents need to make payments without receiving unrestricted wallet authority. AevumPay constrains each payment by token, recipient, exact amount, expiry and one-time request identifier. The agent cannot use the router to redirect or enlarge an approved payment.

## Execution flow
1. Agent submits a payment request to the AevumPay gateway.
2. Gateway constructs a canonical Verigate ActionIntent and requests executable authorization.
3. Gateway verifies the authorization and consumes it once through Verigate.
4. Agent/payer has approved the AevumPay router to spend the exact token amount.
5. The router validates chain, token, recipient, amount, deadline and replay protection.
6. Router calls ERC-20 transferFrom and emits a payment event.

Verigate is an existing external service dependency, not new AevumPay contest implementation. The on-chain router does not claim to verify Verigate's Ed25519 signature. It independently enforces payment constraints.

## Network
QDay Aevum Testnet, chain ID 44005 (0xabe5). Test token tUSD8: `0x456569838f1d43009A91ebA4263147Afd7233483`, 6 decimals. See [network configuration](docs/NETWORK_CONFIG.md).

## Current status
This repository is being restored after recreation. At this point, documentation is being restored; no AevumPay contract has been deployed and no AevumPay testnet transaction has been sent. See [session checkpoint](SESSION-CHECKPOINT.md) for evidence status and next steps.

## Scope and safety
- EOA is the primary execution path.
- ERC-4337/session keys are optional and will only be claimed after a reproducible Aevum UserOperation.
- No custodial escrow.
- No float-based token amounts.
- Fail closed when authorization, signature verification, consume, or chain checks fail.
- Never store private keys, API keys or tenant credentials in the repository.

## Development
The implementation toolchain and exact commands will be pinned with the first executable contract slice. See [architecture](docs/ARCHITECTURE.md), [acceptance criteria](docs/ACCEPTANCE_CRITERIA.md), and [build plan](docs/BUILD_PLAN.md).
