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
