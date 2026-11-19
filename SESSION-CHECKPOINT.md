# AevumPay Session Checkpoint

Last updated: 2026-11-19 (PostgreSQL runtime wiring and reconciliation tests in progress)

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


## Session update — 2026-11-19 (PostgreSQL payment-ledger adapter)

- Re-read this checkpoint first and verified the repository state. Work remains isolated on `feat/postgres-ledger`; `main` was not modified.
- Implemented `gateway/postgres_ledger.py` with `PostgresPaymentStore`: durable payment rows, Fernet-encrypted signed transaction bytes, a linked nonce-reservation table, per-chain/executor advisory locking, and atomic persistence of signed transaction + reservation state.
- Added an authorization-consumed guard: `AUTHORIZED_CONSUMED` cannot be committed unless signed transaction bytes are already durable and the matching nonce reservation is in `SIGNED` state. Both payment and nonce state changes occur in one PostgreSQL transaction.
- Added PostgreSQL 16 integration tests for persistence across store instances, duplicate request IDs, idempotent reservation lookup, nonce allocation across five independent processes, encrypted raw transaction persistence, consume-marker atomicity and nonce audit retention after clearing transaction bytes.
- TDD evidence: the new consume-marker regression test failed before the production guard was added; the expected failure was `DID NOT RAISE ValueError`. After implementation, Gateway CI passed on commit `2a5a90b9af812fdfcffc50f930b13e664945a147`: **38 passed**, Docker image build succeeded. Run: https://github.com/rudimentall1/aevum-agent-payment-gateway/actions/runs/44533226045.
- Solidity CI passed on the same code commit: https://github.com/rudimentall1/aevum-agent-payment-gateway/actions/runs/44533226108.
- Removed destructive `reset_for_test()` methods from both production PostgreSQL store classes; tests now perform table cleanup directly against the dedicated CI database. This cleanup is committed after the green code commit; its latest CI is pending and must be verified before treating the branch HEAD as fully green.
- Updated `docs/POSTGRES_LEDGER_DESIGN.md` to distinguish the implemented adapter from the still-missing Gateway execution integration.
- **Not yet integrated:** `gateway/app.py` still uses SQLite `PaymentStore` and the process-local `EXECUTION_LOCK`. The PostgreSQL adapter is not wired into payment execution, so multi-worker/multi-replica operation remains unsupported.
- No live Verigate, Aevum RPC, contract deployment, testnet payment, or cross-replica crash-recovery flow was exercised.
- Next: verify CI for the cleanup commits; add crash/restart tests against the PostgreSQL ledger itself; then design the explicit runtime backend selection and wire nonce reservation into preflight/sign/persist/consume/broadcast/reconcile without changing the SQLite default. Keep `main` untouched.


## Session update — 2026-11-19 (PostgreSQL runtime wiring)

- Re-read this checkpoint first. Verified main remains at f84159118e18f408ee65e1336ad05f487170de3c; all work below is isolated on feat/postgres-ledger.
- Fixed the incomplete PostgreSQL test-cleanup migration: six integration tests still called the removed production reset_for_test() methods. They now use test-module cleanup helpers. Gateway CI passed on 07733739e9936ec67ca248f9c3adcaa2d9499d75; Solidity CI also passed. Gateway run: https://github.com/rudimentall1/aevum-agent-payment-gateway/actions/runs/44533999342.
- TDD for runtime nonce wiring: added tests for shared PostgreSQL nonce allocation and SQLite fallback. The tests failed on commit 6bfd246df1c919a32b4db54451f958e1186453f8 because reserve_transaction_nonce did not yet exist. This is the observed RED step.
- Wired create_payment_store() into gateway/app.py: AEVUMPAY_DATABASE_URL explicitly selects PostgresPaymentStore; without it, SQLite remains the default. PostgreSQL mode requires AEVUMPAY_TX_ENCRYPTION_KEY.
- Wired preflight_transaction() to read the executor's RPC pending nonce and pass it to the PostgreSQL store's advisory-lock-backed reserve_nonce(). The selected nonce and executor address are returned with the signed transaction. In PostgreSQL mode, the Gateway passes chain ID, executor and nonce to set_signed_transaction(), which atomically stores encrypted signed bytes and transitions the matching reservation to SIGNED. The SQLite method and pending-nonce behavior remain unchanged.
- Added tests for explicit PostgreSQL backend selection and SQLite default selection. Added PostgreSQL-backed Gateway reconciliation tests: no broadcast before the durable consume marker; after creating a new store instance, reconciliation rebroadcasts the exact persisted bytes and verifies terminal ledger/reservation state.
- Updated .env.example, gateway/README.md and docs/POSTGRES_LEDGER_DESIGN.md to describe AEVUMPAY_DATABASE_URL and the actual runtime integration. The standalone PostgresNonceStore remains unused by the HTTP path; runtime uses the linked nonce table in PostgresPaymentStore.
- CI history after runtime wiring exposed test-fixture mismatches (fake preflight return shape and a stale Fernet-key expectation); these were corrected in subsequent commits. Do not cite the intermediate failed runs as current behavior.
- Latest branch HEAD at checkpoint preparation: 09eb3625a7d2119d945aca5b474baf2c28d3ce31. Solidity CI run 44534946082 completed successfully. Gateway CI run 44534946483 is still in progress; its result must be checked before treating the latest code as green.
- Still not verified: full Gateway CI for the latest HEAD; process-level crash/restart under concurrent execution; end-to-end Verigate integration; live QDay RPC; contract deployment; testnet payment. PostgreSQL mode remains experimental and multiple workers/replicas remain unsupported until the full acceptance suite passes.
- Next: inspect Gateway CI for the latest HEAD; fix any failures; then run/extend the complete PostgreSQL acceptance suite for crash points around reservation, signing, consume, broadcast and reconciliation. Keep main untouched.


## Session update — 2026-11-19 (PostgreSQL runtime merged to main)

- Merged PR #4: https://github.com/rudimentall1/aevum-agent-payment-gateway/pull/4
- Merge method: squash. Merge commit / current main HEAD at merge time: `ffaa776aceb197c43c099d41720b4ab62f069321`.
- The 32-commit `feat/postgres-ledger` change set was merged, including PostgreSQL payment storage, linked durable nonce reservations, explicit runtime backend selection, reconciliation after store/process restart, tests, CI PostgreSQL service and documentation.
- SQLite remains the default unless `AEVUMPAY_DATABASE_URL` is explicitly configured. PostgreSQL mode requires `AEVUMPAY_TX_ENCRYPTION_KEY`. Multiple workers/replicas remain unsupported pending cross-process execution-lock and full crash-recovery validation.
- Fixed a malformed Verigate authorization input bug. Before the fix, a non-object authorization envelope or non-object payload raised an uncaught `AttributeError`. Added regression tests first: Gateway CI on test-only commit `e18bb7fc81377322c15b1085f42655415b658bd5` reproduced both failures (**2 failed, 43 passed**). Added explicit dictionary-shape validation in `verify_execution_authorization`; tests now pass.
- Final code HEAD before merge: `f62e6d2f2fef84c86a70a0d95d49f497ada8f685`.
- Gateway CI passed on that exact HEAD: **45 tests passed** and Docker image build succeeded. Push run: https://github.com/rudimentall1/aevum-agent-payment-gateway/actions/runs/44536694896.
- Solidity CI passed on the same HEAD: https://github.com/rudimentall1/aevum-agent-payment-gateway/actions/runs/44536694886. PR-triggered Solidity CI also passed: https://github.com/rudimentall1/aevum-agent-payment-gateway/actions/runs/44536718083.
- Stale PR #3 was closed as superseded by PR #4; no changes were lost because its malformed-envelope hardening is covered by the merged implementation and regression tests.
- The feature branch was merged; `main` is now the integration branch. No live Verigate endpoint, live QDay RPC, deployed router or testnet payment was exercised in this session. Those remain external demo blockers, not CI failures.
- Next: verify post-merge CI on `main`, then proceed to live Verigate/QDay configuration and testnet deployment. Do not enable multi-worker/multi-replica operation until the remaining concurrency acceptance tests pass.


## Session update — 2026-11-19 (nonce-gap fix and testnet deployment automation)

- Current working branch is `main`. The PostgreSQL runtime and Verigate envelope hardening remain integrated.
- Found a critical PostgreSQL nonce-gap bug: a deterministic Verigate rejection before consume left a reserved nonce active. Subsequent payments allocated above the gap and could remain stuck behind the missing nonce.
- TDD evidence for safe release: test-only commit `30bfa88d054320a795a972dd8c3242864dff03c1` failed as expected (**2 failed, 45 passed**) because `release_nonce_reservation` did not exist.
- Implemented safe release: only a payment in REJECTED state with `authorization_consumed=FALSE` can release its reservation. The reservation row is retained as `ABANDONED`; a partial unique index protects active nonce claims, and allocation now chooses the lowest available nonce at or above the RPC pending nonce. Ambiguous consume outcomes keep the reservation and signed bytes.
- Wired the Gateway rejection path to call this release method. Pre-consume preflight HTTP 5xx errors are normalized to a safe pre-consume failure; failures after the consume request begins remain ambiguous and preserve the reservation.
- TDD evidence for legacy migration: test-only commit `0550af554514fb175502bfac58040967f070d085` failed as expected (**47 passed, 1 failed**) because old REJECTED/unconsumed rows remained active.
- Added startup migration to mark legacy REJECTED/unconsumed reservations ABANDONED, so databases created before this fix do not keep nonce gaps forever.
- Gateway CI passed on commit `d9d177bed48a3e3de9444467f9e74c49f0919017`: **48 passed**, PostgreSQL 16 integration tests and Docker image build successful. Run: https://github.com/rudimentall1/aevum-agent-payment-gateway/actions/runs/44538035891.
- Gateway CI passed after app-level release wiring on `4644faa7cd0d9adea0ec86d0cd1210afba8e2896`: **47 passed**, Docker build successful. Run: https://github.com/rudimentall1/aevum-agent-payment-gateway/actions/runs/44537720641.
- Solidity CI passed on `d9d177bed48a3e3de9444467f9e74c49f0919017`: https://github.com/rudimentall1/aevum-agent-payment-gateway/actions/runs/44538036065.
- Added manual GitHub Actions workflow `.github/workflows/qday-testnet-verify.yml` to verify live chain ID, block height, tUSD8 bytecode, name, symbol and decimals from a hosted runner.
- Added guarded manual deployment workflow `.github/workflows/deploy-aevumpay.yml`. It checks the RPC, chain ID, tUSD8 bytecode/decimals, deployer-owner key match and gas balance; deploys the router, enables tUSD8, verifies owner/executor/token support, and publishes deployment artifact/address.
- Deployment workflow requires GitHub Actions secrets `AEVUMPAY_DEPLOYER_PRIVATE_KEY`, `AEVUMPAY_OWNER`, and `AEVUMPAY_EXECUTOR`. Secret values are not present in the repository and must be configured by the owner. Gateway runtime still separately needs `AEVUMPAY_EXECUTOR_PRIVATE_KEY`, `AEVUMPAY_API_KEY`, `AEVUMPAY_TX_ENCRYPTION_KEY`, `VERIGATE_URL`, `VERIGATE_API_KEY`, pinned issuer public key, identity/capability IDs and deployed router address.
- Official QDay site currently confirms Aevum Testnet is live with chain ID 44005 and identifies the QDay testnet RPC; the Builder Challenge page lists tUSD8 at the documented contract address and says the faucet is available. This is external published information, not a successful RPC call from this project runtime.
- Still not live-verified by AevumPay: RPC eth_chainId/block number, tUSD8 bytecode/decimals, router deployment, Verigate authorize/consume, approval and payment receipt. The manual verification workflow must be run in GitHub Actions first; the deployment workflow can then be run after secrets are configured.
- Latest checkpoint preparation HEAD before this append: `d3b2238c275a9144efa2a9d6f16d0860b9537f36`. Gateway CI was running; Solidity CI had passed. Re-check CI on the resulting latest `main` HEAD before calling it green.
- Do not enable multiple Uvicorn workers/replicas until cross-process execution and crash/recovery acceptance tests are complete. PostgreSQL nonce allocation is process-safe; the full Verigate-consume-to-broadcast critical section is not yet proven across multiple replicas.
