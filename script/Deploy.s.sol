// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import "forge-std/Script.sol";
import "forge-std/console2.sol";
import "../src/AevumPayPolicyRouter.sol";

contract DeployAevumPay is Script {
    function run() external returns (AevumPayPolicyRouter router) {
        uint256 deployerKey = vm.envUint("DEPLOYER_PRIVATE_KEY");
        address owner = vm.envAddress("AEVUMPAY_OWNER");
        address executor = vm.envAddress("AEVUMPAY_EXECUTOR");
        address token = vm.envAddress("AEVUMPAY_TOKEN");
        uint256 chainId = vm.envOr("AEVUMPAY_CHAIN_ID", uint256(44005));

        require(owner == vm.addr(deployerKey), "deployer must be owner");

        vm.startBroadcast(deployerKey);
        router = new AevumPayPolicyRouter(owner, executor, chainId);
        router.setTokenSupport(token, true);
        vm.stopBroadcast();

        console2.log("AevumPayPolicyRouter:", address(router));
        console2.log("Owner:", owner);
        console2.log("Executor:", executor);
        console2.log("Allowed token:", token);
        console2.log("Expected chain ID:", chainId);
    }
}
