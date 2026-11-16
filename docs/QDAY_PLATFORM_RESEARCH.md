# QDay Platform Research

## Confirmed from official materials inspected previously
- Aevum is EVM-compatible; Solidity, Foundry, Hardhat, Remix, ethers, viem and wagmi are documented.
- Testnet chain ID is 44005 (0xabe5), RPC and tUSD8 details are in NETWORK_CONFIG.md.
- QDay SDK/CLI packages `@qday-io/sdk` and `@qday-io/cli` were described as planned for Q1 2027; do not make the MVP depend on them.
- Public QDay website currently described native AA/smart-wallet support and x402 as coming soon.
- Older wiki content appeared to describe ERC-4337 smart accounts, session keys, stablecoin paymaster and x402 as live, but did not publish usable EntryPoint, factory, bundler or session-key module addresses/endpoints.
- QDay public pages and old wiki therefore conflict on AA readiness. EOA remains the primary implementation route.
- QDay org demo-paymaster repository inspected previously was configured for Polygon Amoy, not Aevum. Do not copy its chain configuration.

## Decision
Do not block the payment MVP on account abstraction. Revisit only if official Aevum addresses/endpoints become available and an actual UserOperation can be sent and confirmed on testnet.

## Evidence caveat
These findings summarize prior inspection of official pages/repositories. Recheck live documentation before making time-sensitive public claims. No AA deployment or UserOperation has been performed by AevumPay.
