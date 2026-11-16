// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import "forge-std/Test.sol";
import "../src/AevumPayPolicyRouter.sol";

contract MockToken {
    mapping(address => uint256) public balanceOf;
    mapping(address => mapping(address => uint256)) public allowance;
    bool public failTransfer;

    function setFailTransfer(bool value) external { failTransfer = value; }

    function mint(address to, uint256 amount) external { balanceOf[to] += amount; }
    function approve(address spender, uint256 amount) external returns (bool) {
        allowance[msg.sender][spender] = amount;
        return true;
    }
    function transferFrom(address from, address to, uint256 amount) external returns (bool) {
        if (failTransfer) return false;
        require(balanceOf[from] >= amount, "balance");
        require(allowance[from][msg.sender] >= amount, "allowance");
        balanceOf[from] -= amount;
        balanceOf[to] += amount;
        allowance[from][msg.sender] -= amount;
        return true;
    }
}

contract NoReturnToken {
    mapping(address => uint256) public balanceOf;
    mapping(address => mapping(address => uint256)) public allowance;

    function mint(address to, uint256 amount) external { balanceOf[to] += amount; }
    function approve(address spender, uint256 amount) external returns (bool) {
        allowance[msg.sender][spender] = amount;
        return true;
    }
    // Deliberately returns no data, matching legacy ERC-20 implementations.
    function transferFrom(address from, address to, uint256 amount) external {
        require(balanceOf[from] >= amount, "balance");
        require(allowance[from][msg.sender] >= amount, "allowance");
        balanceOf[from] -= amount;
        balanceOf[to] += amount;
        allowance[from][msg.sender] -= amount;
    }
}

contract AevumPayPolicyRouterTest is Test {
    uint256 internal constant CHAIN_ID = 44005;
    uint256 internal payerKey = 0xA11CE;
    address internal payer;
    address internal recipient = address(0xBEEF);
    address internal executor = address(0xE0);
    AevumPayPolicyRouter internal router;
    MockToken internal token;

    function setUp() public {
        vm.chainId(CHAIN_ID);
        payer = vm.addr(payerKey);
        router = new AevumPayPolicyRouter(address(this), executor, CHAIN_ID);
        token = new MockToken();
        router.setTokenSupport(address(token), true);
        token.mint(payer, 10_000_000);
        vm.prank(payer);
        token.approve(address(router), type(uint256).max);
    }

    function _signature(
        address payee,
        uint256 amount,
        bytes32 requestId,
        uint256 deadline
    ) internal returns (bytes memory) {
        bytes32 digest = router.paymentDigest(
            payer, address(token), payee, amount, requestId, deadline
        );
        (uint8 v, bytes32 r, bytes32 s) = vm.sign(payerKey, digest);
        return abi.encodePacked(r, s, v);
    }

    function _execute(
        address payee,
        uint256 amount,
        bytes32 requestId,
        uint256 deadline
    ) internal {
        bytes memory sig = _signature(payee, amount, requestId, deadline);
        vm.prank(executor);
        router.executePayment(payer, address(token), payee, amount, requestId, deadline, sig);
    }

    function testExecutesExactSignedPayment() public {
        bytes32 id = keccak256("payment-1");
        _execute(recipient, 1_250_000, id, block.timestamp + 1 hours);
        assertEq(token.balanceOf(recipient), 1_250_000);
        assertEq(token.balanceOf(payer), 8_750_000);
        assertTrue(router.usedRequestIds(payer, id));
    }

    function testRejectsNonExecutor() public {
        bytes32 id = keccak256("payment-2");
        bytes memory sig = _signature(recipient, 1, id, block.timestamp + 1 hours);
        vm.expectRevert(AevumPayPolicyRouter.Unauthorized.selector);
        router.executePayment(payer, address(token), recipient, 1, id, block.timestamp + 1 hours, sig);
    }

    function testRejectsChangedRecipient() public {
        bytes32 id = keccak256("payment-3");
        bytes memory sig = _signature(recipient, 100, id, block.timestamp + 1 hours);
        vm.prank(executor);
        vm.expectRevert(AevumPayPolicyRouter.InvalidSignature.selector);
        router.executePayment(payer, address(token), address(0xCAFE), 100, id, block.timestamp + 1 hours, sig);
    }

    function testRejectsChangedAmount() public {
        bytes32 id = keccak256("payment-4");
        bytes memory sig = _signature(recipient, 100, id, block.timestamp + 1 hours);
        vm.prank(executor);
        vm.expectRevert(AevumPayPolicyRouter.InvalidSignature.selector);
        router.executePayment(payer, address(token), recipient, 101, id, block.timestamp + 1 hours, sig);
    }

    function testRejectsReplay() public {
        bytes32 id = keccak256("payment-5");
        uint256 deadline = block.timestamp + 1 hours;
        _execute(recipient, 100, id, deadline);
        bytes memory sig = _signature(recipient, 100, id, deadline);
        vm.prank(executor);
        vm.expectRevert(AevumPayPolicyRouter.RequestAlreadyUsed.selector);
        router.executePayment(payer, address(token), recipient, 100, id, deadline, sig);
    }

    function testRejectsExpiredSignature() public {
        bytes32 id = keccak256("payment-6");
        uint256 deadline = block.timestamp + 1;
        vm.warp(deadline + 1);
        bytes memory sig = _signature(recipient, 100, id, deadline);
        vm.prank(executor);
        vm.expectRevert(AevumPayPolicyRouter.Expired.selector);
        router.executePayment(payer, address(token), recipient, 100, id, deadline, sig);
    }

    function testRejectsUnsupportedToken() public {
        bytes32 id = keccak256("payment-7");
        MockToken other = new MockToken();
        bytes32 digest = router.paymentDigest(payer, address(other), recipient, 100, id, block.timestamp + 1 hours);
        (uint8 v, bytes32 r, bytes32 s) = vm.sign(payerKey, digest);
        vm.prank(executor);
        vm.expectRevert(AevumPayPolicyRouter.UnsupportedToken.selector);
        router.executePayment(payer, address(other), recipient, 100, id, block.timestamp + 1 hours, abi.encodePacked(r, s, v));
    }


    function testRejectsWrongChain() public {
        bytes32 id = keccak256("payment-wrong-chain");
        uint256 deadline = block.timestamp + 1 hours;
        bytes memory sig = _signature(recipient, 100, id, deadline);
        vm.chainId(CHAIN_ID + 1);
        vm.prank(executor);
        vm.expectRevert(AevumPayPolicyRouter.InvalidChain.selector);
        router.executePayment(payer, address(token), recipient, 100, id, deadline, sig);
    }

    function testRejectsZeroAmount() public {
        bytes32 id = keccak256("payment-zero");
        uint256 deadline = block.timestamp + 1 hours;
        bytes memory sig = _signature(recipient, 0, id, deadline);
        vm.prank(executor);
        vm.expectRevert(AevumPayPolicyRouter.InvalidAmount.selector);
        router.executePayment(payer, address(token), recipient, 0, id, deadline, sig);
    }

    function testTransferFailureDoesNotConsumeRequest() public {
        bytes32 id = keccak256("payment-token-failure");
        uint256 deadline = block.timestamp + 1 hours;
        bytes memory sig = _signature(recipient, 100, id, deadline);
        token.setFailTransfer(true);
        vm.prank(executor);
        vm.expectRevert(AevumPayPolicyRouter.TokenTransferFailed.selector);
        router.executePayment(payer, address(token), recipient, 100, id, deadline, sig);
        assertFalse(router.usedRequestIds(payer, id));
        assertEq(token.balanceOf(recipient), 0);
    }

    function testRejectsMalformedSignature() public {
        bytes32 id = keccak256("payment-bad-signature");
        vm.prank(executor);
        vm.expectRevert(AevumPayPolicyRouter.InvalidSignature.selector);
        router.executePayment(payer, address(token), recipient, 100, id, block.timestamp + 1 hours, hex"1234");
    }


    function testAcceptsNoReturnERC20() public {
        NoReturnToken legacyToken = new NoReturnToken();
        router.setTokenSupport(address(legacyToken), true);
        legacyToken.mint(payer, 500);
        vm.prank(payer);
        legacyToken.approve(address(router), 500);
        bytes32 id = keccak256("payment-no-return-token");
        uint256 deadline = block.timestamp + 1 hours;
        bytes32 digest = router.paymentDigest(payer, address(legacyToken), recipient, 500, id, deadline);
        (uint8 v, bytes32 r, bytes32 s) = vm.sign(payerKey, digest);
        vm.prank(executor);
        router.executePayment(payer, address(legacyToken), recipient, 500, id, deadline, abi.encodePacked(r, s, v));
        assertEq(legacyToken.balanceOf(recipient), 500);
    }

    function testRejectsZeroRecipient() public {
        bytes32 id = keccak256("payment-zero-recipient");
        uint256 deadline = block.timestamp + 1 hours;
        bytes memory sig = _signature(address(0), 10, id, deadline);
        vm.prank(executor);
        vm.expectRevert(AevumPayPolicyRouter.InvalidRecipient.selector);
        router.executePayment(payer, address(token), address(0), 10, id, deadline, sig);
    }

    function testRejectsRouterAsRecipient() public {
        bytes32 id = keccak256("payment-router-recipient");
        uint256 deadline = block.timestamp + 1 hours;
        bytes memory sig = _signature(address(router), 10, id, deadline);
        vm.prank(executor);
        vm.expectRevert(AevumPayPolicyRouter.InvalidRecipient.selector);
        router.executePayment(payer, address(token), address(router), 10, id, deadline, sig);
    }

    function testOwnerCanPause() public {
        router.setPaused(true);
        bytes32 id = keccak256("payment-8");
        bytes memory sig = _signature(recipient, 100, id, block.timestamp + 1 hours);
        vm.prank(executor);
        vm.expectRevert(AevumPayPolicyRouter.Unauthorized.selector);
        router.executePayment(payer, address(token), recipient, 100, id, block.timestamp + 1 hours, sig);
    }
}
