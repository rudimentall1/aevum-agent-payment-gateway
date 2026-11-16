# AevumPay Session Checkpoint

Last updated: 2026-11-16

## Repository state
- Repository: https://github.com/rudimentall1/aevum-agent-payment-gateway
- Repository was recreated by the owner after intentionally deleting the previous repository.
- Current default branch: main.
- Initial state verified through GitHub: repository exists, public, empty (size 0).
- Previous repository history is not present in this new repository.
- This checkpoint is the first commit in the recreated repository.

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
- Preferred contract is a non-custodial pull-payment policy router. The payer approves the router; router checks recipient, exact amount, expiry, nonce/replay and token, then calls transferFrom.
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
- Aevum RPC and tUSD8 contract: not live-verified from the previous sandbox (DNS resolution failed there; this does not prove global outage).
- AevumPay implementation: not yet written.
- AevumPay contract: not deployed.
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
1. Restore the project documentation into this recreated repository.
2. Establish implementation branch and add the first executable vertical slice.
3. Implement and test the policy router with fail-closed behavior.
4. Confirm live Aevum RPC and tUSD8 metadata from a network-capable environment.
5. Confirm a real self-hosted Verigate endpoint, tenant/auth configuration, DB path and safe identity/capability bootstrap route before integration.
6. Build the EOA -> Gateway -> Verigate authorize/consume -> Aevum policy router -> tUSD8 Transfer flow.
7. Add tests for ALLOW/BLOCK, tampering, replay, expiry, wrong chain/recipient/amount, service outage and RPC timeout reconciliation.
