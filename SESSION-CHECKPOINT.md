# AevumPay Session Checkpoint

Last updated: 2026-11-16 (exact signed transaction flow and encrypted crash reconciliation added)

## Repository state
- Repository: https://github.com/rudimentall1/aevum-agent-payment-gateway
- Repository was recreated by the owner after intentionally deleting the previous repository.
- Current default branch: main.
- Initial state verified through GitHub: repository exists, public, empty (size 0).
- Previous repository history is not present in this new repository.
- Initial checkpoint commit: `65081b984629de6757dca287fd3a980721e523d7`.
- Documentation restoration commits are present on `main` through `15f0b25b4798124b7953051c5afc3daa0dd0660f`.
- Implementation merged to `main` via PR #2: https://github.com/rudimentall1/aevum-agent-payment-gateway/pull/2.
- Merge commit: `3e0966ba329676631c579f2987b4a12639bdf4e4`.
- Earlier conflicting draft PR #1 was closed after PR #2 was verified and merged.

## Project
**AevumPay: Policy-Controlled Payments for AI Agents**

AevumPay is a QDay Aevum testnet payment gateway. It uses an external Verigate authorization service for off-chain agent/action authorization and its own on-chain policy router for deterministic payment constraints. Verigate is an existing external dependency and is not represented as new AevumPay contest implementation.

## Competition
- QDay Aevum Builder Challenge #1.
- Build window: 2026-11-16 through 2026-12-11.
- Submission closes: 2026-12-11 08:00 UTC.
- Judging: 2026-12-12 through 2026-12-14.
- Demo Day: 2026-12-15 06:00 UTC.
- Prize pool: 1,500 USDT.
- Public repository, Aevum integration, runnable demo/prototype or Docker image, documentation, demo video/pitch, and testnet smart contracts are expected.
- Organizer confirmed existing Verigate authorization may be used through an API, but is outside the new hackathon implementation scope.

## Network configuration (starter-kit documented; live RPC not yet verified)
- Network: QDay Aevum Testnet
- Chain ID: 44005 (0xabe5)
- RPC: https://rpc-test.qday.info
- WebSocket: wss://rpc-test.qday.info
- Native gas token: tQDAY
- Explorer: https://explorer-test.qday.info/
- Faucet: https://faucet.qday.info/en
- tUSD8: 0x456569838f1d43009A91ebA4263147Afd7233483
- tUSD8 decimals: 6

## Architecture decisions
- Primary execution path is EOA-based. ERC-4337 / session-key support is optional only if official Aevum testnet endpoints and addresses are published and a real UserOperation can be reproduced.
- Preferred contract is a non-custodial pull-payment policy router. The payer approves the router and signs an EIP-712 envelope binding payer, token, recipient, amount, request ID, deadline, chain ID and router address. The configured executor relays it; router checks signature, recipient, exact amount, expiry, replay and token, then calls transferFrom.
- Funds remain in the payer account until execution. No custodial escrow.
- Verigate authorization and on-chain payment enforcement are separate trust boundaries.
- Do not claim the EVM contract verifies Verigate Ed25519 signatures.
- Do not claim AA/session-key integration without a confirmed on-chain UserOperation.

## Verigate integration findings (source-inspected; not live-integrated)
- Use POST /v1/actions/authorize, not legacy POST /v1/authorize, for executable payment authority.
- Verify the Ed25519 execution authorization and then call POST /v1/execution/consume with the exact envelope. Continue only when execute=true.
- Consume is one-time authorization consumption; it does not broadcast an EVM transaction.
- Use amount_exact as a decimal string. Do not use floating-point amounts.
- Action metadata must include network_family=evm and evm_transaction with chain_id=44005, router destination, value_wei=0 and exact calldata.
- Verigate ActionIntent target should be the payment recipient; evm_transaction.to is the AevumPay router.
- Verigate generic EVM fallback appears to support unknown network names when valid EVM metadata is supplied; this requires integration testing.
- Identity and capability provisioning currently requires direct registry/storage access on the self-hosted Verigate instance; no public REST registration endpoint was found.
- Verigate README describes its generic API as a protocol implementation/demo, not a hosted multi-tenant service. Do not assume a vendor-hosted endpoint.
- Python and JavaScript JSON number serialization can differ for timestamp floats. Prefer a pinned Verigate Python signer or exact canonicalization fixtures.

## Evidence status
- Official starter-kit and public QDay documentation: inspected in the prior work session.
- Verigate source/routes/schemas/engine/execution router/identity/capability/signing code: inspected in the prior work session.
- Aevum RPC and tUSD8 contract: not live-verified. DNS resolution for `rpc-test.qday.info` failed in prior attempts and again in this session from the container (`Temporary failure in name resolution`). This does not prove a global outage.
- AevumPay implementation is merged to `main`: EIP-712 policy router, 15 Foundry tests, deployment script, threat model and Solidity CI workflow.
- GitHub Actions on the merged implementation branch completed `forge build --sizes` successfully and all 15 Foundry tests passed (run: https://github.com/rudimentall1/aevum-agent-payment-gateway/actions/runs/43840838263).
- PR #2 was mergeable/clean and merged by squash. No deployment or live transaction is claimed.
- Contract is not deployed.
- Foundry coverage includes executor restrictions, signature tampering, replay, expiry, unsupported token, wrong chain, zero amount, malformed signature, failed-transfer rollback, no-return ERC-20 compatibility and recipient restrictions. Tests have not been run locally in this runtime.
- Solidity CI runs `forge build --sizes` and `forge test -vvv` on pull requests and pushes to `main` and `feat/**`.
- Initial FastAPI gateway is implemented under `gateway/`: typed-data, prepare, execute, status and health endpoints. It derives calldata, enforces decimal-string amounts, verifies payer EIP-712 signatures and pinned Verigate Ed25519 execution authorizations, calls Verigate authorize/consume, submits the transaction and records payment status in SQLite.
- Gateway verifies the exact ERC-20 Transfer and PaymentExecuted events before marking a payment CONFIRMED. It performs chain, executor, pause, token, balance, allowance and gas preflight, signs the exact transaction before Verigate consume, and does not rebuild nonce/gas/calldata after consume.
- Signed raw transaction bytes are encrypted in SQLite using Fernet and the separately configured `AEVUMPAY_TX_ENCRYPTION_KEY`; public status responses never return the raw bytes.
- Ledger records `SIGNED_AWAITING_CONSUME` before the one-time Verigate consume. Only after consume returns `execute=true` does it durably set `authorization_consumed=1`, then broadcast the exact signed bytes.
- `POST /v1/payments/{request_id}/reconcile` re-broadcasts only the identical stored signed bytes and verifies the receipt/events, and only when the ledger durably records successful consume. If a crash occurs after Verigate consumed but before that marker is written, automated recovery refuses to proceed; manual Verigate reconciliation is required.
- Gateway CI passed on commit `b992dc53a6b13c339198f11488b8309a9673581b`: unit tests and Docker image build succeeded. Run: https://github.com/rudimentall1/aevum-agent-payment-gateway/actions/runs/44035125830.
- Later Gateway CI passed on commit `8b524fa207af6d4148abe36f4b5d0a09c4c59b7c`: 23 Gateway tests and Docker build succeeded. Run: https://github.com/rudimentall1/aevum-agent-payment-gateway/actions/runs/44036014605.
- Gateway CI passed on commit `98d19b736f184f7c510b7f440cb3fa4003aa15ec`: 26 tests and Docker build succeeded. Run: https://github.com/rudimentall1/aevum-agent-payment-gateway/actions/runs/44036754108.
- Gateway CI passed on commit `9e167f51ede5acd95c0365776b0cd991e5494152`: 27 tests and Docker build succeeded. Run: https://github.com/rudimentall1/aevum-agent-payment-gateway/actions/runs/44037402225.
- Gateway CI passed on commit `c15c28cf3299f40f02c559af0464fb4e0e66e33e`: 29 tests and Docker build succeeded. Run: https://github.com/rudimentall1/aevum-agent-payment-gateway/actions/runs/44048575495.
- No live Verigate endpoint, QDay RPC, deployed router or payment has been exercised.
- A non-root Dockerfile, Compose service, `.env.example` and runtime setup guide are present. Docker image build is CI-verified; Compose has not been started with live credentials.
- Gateway is not yet live-integrated: no Verigate URL, API key, tenant, issuer public key, router address or executor key has been configured.
- No testnet transaction has been sent by AevumPay.
- No production secrets, API keys or private keys are recorded here.

## Session operating rule
At the beginning of every session:
1. Read this checkpoint first.
2. Verify current GitHub HEAD and recent commits; never rely on this file alone.
3. Inspect only relevant files and avoid repeating completed checks without reason.
4. Update this checkpoint after substantial work with exact commit/test/deployment/transaction evidence.
5. Distinguish documented/source-inspected, locally tested, integration-tested, live testnet and independently verified.
6. Never claim work or external verification that did not occur.

## Next actions
1. Finish the PostgreSQL payment ledger and transactionally persist payment state, encrypted raw transaction bytes, authorization-consumed marker and nonce reservation before enabling shared execution.
2. Verify Aevum RPC `eth_chainId`, `eth_blockNumber`, tUSD8 bytecode and decimals from a network-capable host.
3. Confirm the actual self-hosted Verigate endpoint, API key, tenant, issuer public key and exact tenant DB path; provision the identity and capability against that running instance.
4. Deploy the router to Aevum testnet using privately configured deployer values; record contract address and deployment receipt.
5. Populate `.env` and the pinned issuer public-key file privately; launch Compose only after router and Verigate endpoint are verified.
6. Run authorize/verify/consume integration tests against the real Verigate instance.
7. Execute a small tUSD8 payment on testnet; verify receipt, exact ERC-20 Transfer and PaymentExecuted logs, and reconciliation endpoint behavior.
8. Do not enable multiple workers or replicas until the complete PostgreSQL ledger and crash-recovery acceptance tests pass.


## Session update — 2026-11-17 (PostgreSQL nonce reservation primitive)

- Work is isolated on branch `feat/postgres-ledger`; `main` has not been modified.
- Added `docs/POSTGRES_LEDGER_DESIGN.md` describing the required shared-ledger invariants, transaction protocol, crash handling and rollout gates.
- Added `gateway/postgres_nonce.py`, an isolated PostgreSQL nonce reservation primitive. It uses a transaction-scoped advisory lock per chain/executor, a unique nonce key and a globally unique request ID. Reservations persist across store/process restarts.
- Added PostgreSQL integration tests using six independent spawned processes, duplicate request ID rejection and reservation persistence after constructing a new store.
- Added psycopg v3 to production gateway requirements and a PostgreSQL 16 service to Gateway CI.
- Verified CI run `44054246429` on commit `d30bd21b75dd94c8b785744f33cf94634f4dc44c`: **32 passed**, 1 warning; Docker image build succeeded. Run: https://github.com/rudimentall1/aevum-agent-payment-gateway/actions/runs/44054246429.
- This verifies the isolated nonce primitive against real PostgreSQL in CI. It does not verify payment-ledger persistence, consume/reconciliation across replicas, live QDay RPC or live Verigate.
- The primitive is deliberately not wired into `gateway/app.py`; current SQLite payment execution and its one-worker/one-replica constraint remain unchanged.
- The design document's status is updated to distinguish the implemented nonce primitive from the still-unimplemented PostgreSQL payment ledger.
- Next bounded work: implement the PostgreSQL payment-ledger adapter and state transitions with crash-recovery tests before changing the payment execution path. Keep `main` untouched.
