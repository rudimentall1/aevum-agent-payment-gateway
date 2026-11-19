# QDay Aevum Testnet

Values below are documented by the official Builder Challenge Starter Kit V3 and QDay public documentation. They are **not yet live-RPC verified** from this project environment.

| Setting | Value |
|---|---|
| Network | QDay Aevum Testnet |
| Chain ID (decimal) | 44005 |
| Chain ID (hex) | 0xabe5 |
| HTTP RPC | https://rpc-test.qday.info |
| WebSocket RPC | wss://rpc-test.qday.info |
| Native gas token | tQDAY |
| Explorer | https://explorer-test.qday.info/ |
| Faucet | https://faucet.qday.info/en |
| tUSD8 | 0x456569838f1d43009A91ebA4263147Afd7233483 |
| tUSD8 decimals | 6 |

## Verification still required
From a network-capable environment, verify:
- `eth_chainId` returns `0xabe5`.
- `eth_blockNumber` returns a valid block.
- tUSD8 has non-empty bytecode at the published address.
- ERC-20 `decimals()` returns 6 and `symbol()`/ `name()` are recorded.
- Faucet can fund a test wallet.
- A small test transfer is confirmed and visible in the explorer.

Do not interpret a DNS failure in one sandbox as proof that the public RPC is down. Do not claim a live transaction until its receipt and explorer record are checked.

## Official resources
- QDay: https://qday.io/
- Builder Challenge: https://qday.io/builder-challenge
- Developer guide: https://wiki.qday.info/Knowledge/technical/developer-guide/smart-contract-development/
- SDK examples: https://wiki.qday.info/Knowledge/technical/developer-guide/sdk-code-examples/
- Wallet integration: https://wiki.qday.info/Knowledge/technical/developer-guide/wallet-integration
- GitHub: https://github.com/qday-io
- Discord: https://discord.gg/bYPhjmrSfK


## Repository-assisted verification and deployment

Two manual GitHub Actions workflows are provided:

- **Verify QDay Testnet** (`.github/workflows/qday-testnet-verify.yml`) checks the live RPC chain ID, latest block, tUSD8 bytecode and ERC-20 name/symbol/decimals. Run it from the repository's Actions tab before deploying.
- **Deploy AevumPay Router** (`.github/workflows/deploy-aevumpay.yml`) validates the RPC and tUSD8, checks the deployer/owner match and gas balance, deploys the router, enables tUSD8, then verifies owner, executor and token allowlist. It publishes the router address and deployment artifact.

The deployment workflow requires these GitHub Actions repository secrets:

- `AEVUMPAY_DEPLOYER_PRIVATE_KEY` — funded testnet deployer key; must correspond to the owner address.
- `AEVUMPAY_OWNER` — public address derived from the deployer key.
- `AEVUMPAY_EXECUTOR` — public EOA address that will be configured as the router executor.

Never put private keys in workflow inputs, repository files, issues, or chat. After deployment, copy the verified router address into the Gateway runtime as `AEVUMPAY_ROUTER_ADDRESS`; the executor private key configured in the Gateway must correspond to `AEVUMPAY_EXECUTOR`.
