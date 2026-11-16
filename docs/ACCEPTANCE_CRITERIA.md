# Acceptance Criteria

## Contract
- [ ] Deploys to QDay Aevum testnet and verified chain ID is 44005.
- [ ] Only allowlisted token can be used.
- [ ] Zero recipient, zero amount, expired request and reused request ID revert.
- [ ] Amount and recipient cannot be altered after authorization.
- [ ] Reentrancy and unsafe ERC-20 return behavior are handled.
- [ ] Successful transfer emits a payment event and matching ERC-20 Transfer.
- [ ] Contract does not custody balances beyond transaction execution.

## Gateway
- [ ] Amount parsing is decimal-string only and exact to token precision.
- [ ] Arbitrary target/calldata is rejected.
- [ ] Verigate authorize endpoint used; legacy endpoint not used.
- [ ] Ed25519 signature is verified against a pinned issuer key.
- [ ] Exact authorization envelope is consumed once.
- [ ] Submission occurs only after execute=true.
- [ ] Service errors fail closed.
- [ ] RPC timeout leads to reconciliation, not blind retry.

## Integration evidence
- [ ] Aevum RPC chain ID and block number recorded.
- [ ] Token bytecode and decimals verified.
- [ ] Router deployment address and transaction receipt recorded.
- [ ] Approval transaction recorded.
- [ ] Payment transaction receipt, Transfer event and router event recorded.
- [ ] Explorer links independently open.

## Delivery
- [ ] Public GitHub repository.
- [ ] Reproducible test command and CI.
- [ ] Runnable demo or Docker image.
- [ ] Architecture, threat model and setup docs.
- [ ] Demo video and pitch.
- [ ] Claims match the evidence actually collected.
