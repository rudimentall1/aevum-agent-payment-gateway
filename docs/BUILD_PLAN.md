# Build Plan

## Milestone 0 — repository and toolchain
- Restore docs and checkpoint.
- Pin Solidity toolchain and dependencies.
- Add formatting, unit-test and CI commands.
- Keep secrets out of Git.

## Milestone 1 — policy router vertical slice
- Implement configurable token allowlist.
- Implement non-custodial `pay` path using SafeERC20.
- Bind payer, token, recipient, amount, request ID and expiry.
- Add replay protection and reentrancy protection.
- Add events and custom errors.
- Unit-test success and every revert condition.

## Milestone 2 — gateway API
- Strict request schema; decimal string amounts only.
- Convert to base units without float.
- Build canonical Verigate ActionIntent.
- Call authorize, verify execution authorization, then consume exact envelope.
- Fail closed unless consume returns execute=true.
- Submit exact router calldata and persist transaction/request state.

## Milestone 3 — end-to-end testnet
- Verify Aevum RPC and tUSD8 live.
- Deploy router and record chain/address/transaction.
- Fund a test EOA and approve router.
- Execute small payment; verify receipt, Transfer and router event.
- Demonstrate blocked recipient/amount/replay/expiry cases.

## Milestone 4 — Verigate integration
- Confirm reachable self-hosted Verigate endpoint and tenant/auth model.
- Provision identity/capability using the actual API database.
- Pin signer/canonicalization implementation.
- Test authorize + signature verification + consume.
- Never store credentials or signing keys in GitHub.

## Milestone 5 — judge-ready package
- Docker Compose demo with explicit environment variables.
- Reproducible local tests.
- Architecture and threat model.
- Demo script/video and concise pitch.
- Submission checklist and evidence links.

## Parallel research gate: account abstraction
Spend a short, bounded effort confirming official Aevum AA endpoints and addresses. If no reproducible path exists, retain EOA-first MVP and do not let AA research block the payment vertical slice.
