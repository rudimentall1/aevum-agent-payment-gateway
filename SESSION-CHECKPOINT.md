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
- AevumPay contract: not deployed.
- Foundry coverage includes executor restrictions, signature tampering, replay, expiry, unsupported token, wrong chain, zero amount, malformed signature, failed-transfer rollback, no-return ERC-20 compatibility and recipient restrictions. GitHub Actions executed and passed all 15 tests. Tests have not been run locally in this runtime.
- Solidity CI runs `forge build --sizes` and `forge test -vvv` on pull requests and pushes to `main` and `feat/**`. Latest main run passed: https://github.com/rudimentall1/aevum-agent-payment-gateway/actions/runs/43841842492.
- Initial FastAPI gateway is implemented under `gateway/`: `/v1/payments/typed-data`, `/v1/payments/prepare`, `/v1/payments/execute`, `/v1/payments/{request_id}` and `/health`. It derives calldata, enforces decimal-string amounts, verifies payer EIP-712 signatures and pinned Verigate Ed25519 execution authorizations, calls Verigate authorize/consume, submits the transaction and records payment status in SQLite.
- Gateway verifies the exact ERC-20 Transfer and PaymentExecuted events before marking a payment CONFIRMED. It performs chain, executor, pause, token, balance, allowance and gas preflight, signs the exact transaction before Verigate consume, and does not rebuild nonce/gas/calldata after consume.
- Signed raw transaction bytes are encrypted in SQLite using Fernet and the separately configured `AEVUMPAY_TX_ENCRYPTION_KEY`; public status responses never return the raw bytes.
- Ledger records `SIGNED_AWAITING_CONSUME` before the one-time Verigate consume. Only after consume returns `execute=true` does it durably set `authorization_consumed=1`, then broadcast the exact signed bytes.
- `POST /v1/payments/{request_id}/reconcile` was added. It re-broadcasts only the identical stored signed bytes and verifies the receipt/events, and only when the ledger durably records successful consume. If a crash occurs after Verigate consumed but before that marker is written, automated recovery refuses to proceed; manual Verigate reconciliation is required.
- Gateway CI passed the earlier 5-test suite and built the Docker image on commit `47dfc9922f35a6b428ab4da92fea8f3c96f5768d`: https://github.com/rudimentall1/aevum-agent-payment-gateway/actions/runs/43842350154.
- After exact signed-transaction persistence, encryption and reconciliation changes, Gateway CI passed its unit-test step on commit `3d38cfa2c186846d20e69890bf24cfafdcc016ba`; Docker image build was still running when last checked: https://github.com/rudimentall1/aevum-agent-payment-gateway/actions/runs/43856166920. The latest documentation commit has a new CI run queued; do not call the latest HEAD fully green until it completes.
- Solidity CI also passed on that commit: https://github.com/rudimentall1/aevum-agent-payment-gateway/actions/runs/43842350189.
- A non-root Dockerfile, Compose service, `.env.example` and runtime setup guide are present. Docker image build is CI-verified; Compose has not been started with live credentials.
- Gateway is not yet live-integrated: no Verigate URL, API key, tenant, issuer public key, router address or executor key has been configured. No Aevum testnet deployment or payment has occurred.
- Verigate live integration: not configured or tested.
- No testnet transaction has been sent by AevumPay.
- Gensyn2 Desktop Commander connection was unavailable in the previous session. No secrets, API keys or private keys are recorded here.

## Session operating rule
At the beginning of every session:
1. Read this checkpoint first.
2. Verify current GitHub HEAD and recent commits; never rely on this file alone.
3. Inspect only relevant files and avoid repeating completed checks without reason.
4. Update this checkpoint after substantial work with exact commit/test/deployment/transaction evidence.
5. Distinguish documented/source-inspected, locally tested, integration-tested, live testnet and independently verified.
6. Never claim work or external verification that did not occur.

## Next actions
1. Verify the latest `main` Gateway CI and Docker image build; current latest-docs commit run is queued.
2. Verify Aevum RPC `eth_chainId`, `eth_blockNumber`, tUSD8 bytecode and decimals from a network-capable host; this execution environment cannot resolve the RPC hostname.
3. Confirm the actual self-hosted Verigate endpoint, API key, tenant, issuer public key and exact tenant DB path; provision the identity and capability against that running instance.
4. Deploy the router to Aevum testnet using privately configured deployer values; record contract address and deployment receipt.
5. Populate `.env` and the pinned issuer public-key file privately; launch Compose only after router and Verigate endpoint are verified.
6. Run authorize/verify/consume integration tests against the real Verigate instance.
7. Execute a small tUSD8 payment on testnet; verify receipt, exact ERC-20 Transfer and PaymentExecuted logs, and reconciliation endpoint behavior.
8. Expand gateway tests for DENY, malformed/invalid issuer signatures, consume=false, service timeouts, RPC ambiguity and process-crash recovery.


## Session update — 2026-11-17

- Verified the repository still exists and is public. Current work is on the recreated repository; it does not contain the pre-deletion Git history.
- Latest HEAD before this session's documentation correction was `711087c18d345aa6762c26b1356aa00d8acc56b6` (checkpoint update, 2026-11-16 11:16 UTC).
- Updated README on 2026-11-17 in commit `b0a2955ccead4fe92afc4262dc2ed954f209d997`: corrected the order of payer signing, agent signing, Verigate authorization/consume and transaction broadcast; documented the implemented Gateway and its evidence boundaries.
- Verified GitHub Actions run `43856166920`: Gateway unit-test job and Docker image build both completed successfully. This run is associated with the gateway implementation commit `3d38cfa2c186846d20e69890bf24cfafdcc016ba`, not the latest README commit.
- Verified GitHub Actions run `43841842492`: Foundry build and all 15 Solidity tests completed successfully. This is recorded historical CI evidence, not a local test run.
- The GitHub connector did not return workflow runs or commit statuses for latest documentation HEAD `711087c`; do not claim that HEAD has a fresh green CI run.
- Desktop Commander was checked again on 2026-11-17. No devices are connected, so Gensyn2 cannot be inspected from this session.
- Current blocking dependencies remain unchanged: live Aevum RPC/token verification, a reachable self-hosted Verigate endpoint with matching identity/capability/database context, router deployment, and a live testnet payment.
- Code review observation: the README's former sequence implied Verigate consume happened before the payer signed the EIP-712 envelope. That documentation inconsistency is fixed in `b0a2955`. No application code was changed in this session.
- Next: connect Gensyn2 Desktop Commander; inspect Verigate process/config/database path without exposing secret values; then verify Aevum RPC and token from a network-capable host. Do not attempt deployment or payment until both dependencies are confirmed.


## Session update — 2026-11-17 (Verigate authorization test coverage)

- Current main HEAD after this work: 4ca86da9fa7dc1343a8e9b7848ed2910dea4d263.
- Added five focused tests to gateway/tests/test_gateway.py for the existing verify_execution_authorization boundary:
  - accepts a valid Ed25519 authorization signed by the pinned public key;
  - rejects an action/transaction substitution;
  - rejects a modified signature;
  - rejects an unsupported signature algorithm;
  - rejects an action fingerprint mismatch even when the altered payload itself has a valid signature.
- Test changes are committed directly to main in:
  - 0eeca3a4240e16cd4b467b8d493c01135e641a69 (initial test addition);
  - c6b19472f3058f6b923ca9d773548151e762fcfa (fingerprint test refinement);
  - 4ca86da9fa7dc1343a8e9b7848ed2910dea4d263 (corrected helper unpacking).
- Sandbox worktree at /mnt/data/aevumpay-sandbox contains a focused snapshot of the verifier and its five tests. The isolated sandbox test run passed: 5 passed in 0.20s. This is not a full repository checkout and is not a substitute for the repository's full Gateway CI.
- The sandbox Python environment lacks web3, eth-account, and eth-abi, so the complete gateway/tests suite could not be run locally in this runtime. GitHub Actions Gateway CI was triggered for HEAD 4ca86da and was still in progress at the time of this checkpoint update: https://github.com/rudimentall1/aevum-agent-payment-gateway/actions/runs/44034600885.
- Solidity CI for the same HEAD completed successfully: https://github.com/rudimentall1/aevum-agent-payment-gateway/actions/runs/44034600960.
- No production code was changed. No Verigate endpoint, QDay RPC, contract deployment, or live payment was exercised.

- Follow-up verification: Gateway CI run 44034600885 completed successfully for test commit 4ca86da9fa7dc1343a8e9b7848ed2910dea4d263. Both the full Gateway unit-test step and Docker image build passed. Run URL: https://github.com/rudimentall1/aevum-agent-payment-gateway/actions/runs/44034600885.
- Latest main HEAD after the checkpoint-only follow-up is d1939470b891e02826c1eef17cc7ef96cf41c01a. The successful Gateway CI is tied to the immediately preceding code/test commit 4ca86da, not the docs-only checkpoint commit.


## Session update — 2026-11-17 (definitive rejection cleanup)

- Added an integration-style regression test for a definitive Verigate 403 after the exact signed transaction has been persisted. The test was first run in CI on commit 0dffc0fb54301a36b1cb9e1422a00984863c793e and failed, reproducing the bug: the rejected payment retained encrypted signed transaction bytes.
- Fixed gateway/app.py in commit 1ecac49c319a094b563fad6e1118e7439f2bd697: when execute() receives a deterministic HTTP error (<500), it records REJECTED and clears the persisted signed transaction. HTTP errors >=500 remain UNKNOWN_REQUIRES_RECONCILIATION and preserve bytes because Verigate consume may have succeeded despite a timeout/transport failure.
- Added a second regression test in commit b992dc53a6b13c339198f11488b8309a9673581b proving ambiguous 502 consume outcome preserves the encrypted transaction for manual reconciliation and does not set authorization_consumed.
- Gateway CI passed on b992dc53a6b13c339198f11488b8309a9673581b: unit tests and Docker image build succeeded. Run: https://github.com/rudimentall1/aevum-agent-payment-gateway/actions/runs/44035125830.
- Solidity CI passed on the same commit: https://github.com/rudimentall1/aevum-agent-payment-gateway/actions/runs/44035125842.
- Sandbox at /mnt/data/aevumpay-sandbox now includes the earlier Ed25519 verifier snapshot plus a focused copy of the execute failure-state policy and two tests. Full sandbox pytest result: 7 passed in 0.28s. This is an isolated policy/verifier snapshot, not a full checkout; repository Gateway CI is the authoritative full-suite result.
- No live Verigate endpoint, Aevum RPC, deployment, or payment was used. No production secrets were accessed.
- Current main code/test commit: b992dc53a6b13c339198f11488b8309a9673581b. Checkpoint-only commit follows.


## Session update — 2026-11-17 (Verigate HTTP boundary coverage)

- Added HTTP-level tests around `authorize_and_consume` in `gateway/tests/test_gateway.py`:
  - valid ALLOW + pinned Ed25519 authorization + consume execute=true;
  - DENY without a consume request;
  - identity, capability, agent and intent binding mismatches;
  - invalid issuer signature rejected before consume;
  - consume execute=false;
  - consume transport failure and timeout fail closed.
- The test additions exposed two test-fixture issues during CI (missing `httpx` import and incomplete action envelope); both were corrected. The earlier failing CI runs correspond to intermediate commits and are not the current result.
- Latest code/test commit: `8b524fa207af6d4148abe36f4b5d0a09c4c59b7c`.
- Gateway CI passed on that commit: all 23 Gateway tests passed and the Docker image built successfully. Run: https://github.com/rudimentall1/aevum-agent-payment-gateway/actions/runs/44036014605.
- Solidity CI passed on the same commit. Run: https://github.com/rudimentall1/aevum-agent-payment-gateway/actions/runs/44036015013.
- No production application code changed in this slice. No live Verigate endpoint, Aevum RPC, contract deployment or testnet payment was exercised.
- Current scope remains mock-HTTP boundary coverage; it is not a live Verigate integration test.


## Session update — 2026-11-17 (Verigate pre-consume failure classification)

- Added regression coverage for failures before the /v1/execution/consume request: authorize timeout, authorize HTTP failure, malformed authorize JSON, and invalid issuer signature. The tests first failed on the old behavior (all were surfaced as HTTP 502).
- Updated authorize_and_consume to track whether consume has started:
  - Before consume starts, unexpected authorize/validation/transport failures return HTTP 424 (Failed Dependency). The execute handler treats this as a definitive pre-consume failure and clears the persisted signed transaction.
  - Immediately before sending the consume request, the function marks the stage as potentially ambiguous. Any unexpected exception from then onward returns HTTP 502, preserving the signed transaction for reconciliation.
  - Explicit policy DENY / identity binding mismatch and explicit consume execute=false retain their existing 403 behavior.
- Latest code/test commit: 98d19b736f184f7c510b7f440cb3fa4003aa15ec.
- Gateway CI passed: 26 tests passed; Docker image build succeeded. Run: https://github.com/rudimentall1/aevum-agent-payment-gateway/actions/runs/44036754108.
- Solidity CI passed. Run: https://github.com/rudimentall1/aevum-agent-payment-gateway/actions/runs/44036754086.
- The earlier red runs are intentional TDD evidence: first the new pre-consume cases failed (3 failures), then the implementation exposed one outdated expected status; corrected tests pass on the latest commit.
- Still not exercised: live Verigate service, live QDay RPC, deployed router, or testnet payment. This is mocked HTTP boundary coverage only.

## Session update — 2026-11-17 (executor nonce concurrency)

- Verified current main before this slice: `e9eefd9d30fd137b11a790ebf2385bb6c13fa226`; both Gateway and Solidity CI were green on that HEAD.
- Added a concurrent-execution regression test in `gateway/tests/test_gateway.py`. It deliberately blocks the first payment during preflight and verifies that a second request cannot enter nonce preflight before the first request finishes the critical section.
- The regression test failed on the unmodified implementation on commit `d62475db04ea122c6d6f684460b8e0ab1d15595f`: 1 failed, 26 passed. CI log showed the second request entered preflight while the first was unresolved, confirming the race.
- Fixed `gateway/app.py` in commit `9e167f51ede5acd95c0365776b0cd991e5494152`: introduced an in-process execution lock held from nonce lookup/signing through Verigate consume and transaction broadcast. Locking only the preflight function would not be sufficient because the RPC pending nonce may not advance while the first transaction is waiting on Verigate.
- Gateway CI passed on `9e167f51ede5acd95c0365776b0cd991e5494152`: 27 tests passed and Docker image build succeeded. Run: https://github.com/rudimentall1/aevum-agent-payment-gateway/actions/runs/44037402225.
- Solidity CI passed on the same commit. Run: https://github.com/rudimentall1/aevum-agent-payment-gateway/actions/runs/44037402131.
- README now documents the operational constraint: one Uvicorn worker and one running replica. The lock is process-local; horizontal scaling is not safe until a shared durable nonce-reservation mechanism is implemented.
- This is a code-path fix verified in CI, not a live-chain concurrency test. No Verigate endpoint, Aevum RPC, deployment or payment was exercised.
