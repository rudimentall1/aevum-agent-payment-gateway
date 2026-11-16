// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

/// @title AevumPayPolicyRouter
/// @notice Non-custodial, EIP-712-authorized ERC-20 payments for QDay Aevum.
/// @dev The router never holds funds. A configured executor may relay a payment
///      only with the payer's signature over the exact payment envelope.
contract AevumPayPolicyRouter {
    error Unauthorized();
    error ZeroAddress();
    error InvalidChain(uint256 actual, uint256 expected);
    error UnsupportedToken(address token);
    error InvalidRecipient();
    error InvalidAmount();
    error Expired(uint256 deadline);
    error RequestAlreadyUsed(address payer, bytes32 requestId);
    error InvalidSignature();
    error TokenTransferFailed();
    error ReentrantCall();

    uint256 private constant SECP256K1_HALF_N =
        0x7fffffffffffffffffffffffffffffff5d576e7357a4501ddfe92f46681b20a0;

    bytes32 public constant PAYMENT_TYPEHASH = keccak256(
        "Payment(address payer,address token,address recipient,uint256 amount,bytes32 requestId,uint256 deadline)"
    );
    bytes32 private constant DOMAIN_TYPEHASH = keccak256(
        "EIP712Domain(string name,string version,uint256 chainId,address verifyingContract)"
    );
    bytes32 private constant NAME_HASH = keccak256("AevumPayPolicyRouter");
    bytes32 private constant VERSION_HASH = keccak256("1");

    address public owner;
    address public executor;
    uint256 public immutable expectedChainId;
    bool public paused;
    uint256 private lockState = 1;

    mapping(address => bool) public supportedTokens;
    mapping(address => mapping(bytes32 => bool)) public usedRequestIds;

    event OwnershipTransferred(address indexed previousOwner, address indexed newOwner);
    event ExecutorUpdated(address indexed previousExecutor, address indexed newExecutor);
    event TokenSupportUpdated(address indexed token, bool supported);
    event PauseUpdated(bool paused);
    event PaymentExecuted(
        address indexed payer,
        address indexed token,
        address indexed recipient,
        uint256 amount,
        bytes32 requestId
    );

    modifier onlyOwner() {
        if (msg.sender != owner) revert Unauthorized();
        _;
    }

    modifier nonReentrant() {
        if (lockState != 1) revert ReentrantCall();
        lockState = 2;
        _;
        lockState = 1;
    }

    constructor(address initialOwner, address initialExecutor, uint256 chainId) {
        if (initialOwner == address(0) || initialExecutor == address(0)) revert ZeroAddress();
        if (block.chainid != chainId) revert InvalidChain(block.chainid, chainId);
        owner = initialOwner;
        executor = initialExecutor;
        expectedChainId = chainId;
        emit OwnershipTransferred(address(0), initialOwner);
        emit ExecutorUpdated(address(0), initialExecutor);
    }

    function transferOwnership(address newOwner) external onlyOwner {
        if (newOwner == address(0)) revert ZeroAddress();
        emit OwnershipTransferred(owner, newOwner);
        owner = newOwner;
    }

    function setExecutor(address newExecutor) external onlyOwner {
        if (newExecutor == address(0)) revert ZeroAddress();
        emit ExecutorUpdated(executor, newExecutor);
        executor = newExecutor;
    }

    function setTokenSupport(address token, bool supported) external onlyOwner {
        if (token == address(0)) revert ZeroAddress();
        supportedTokens[token] = supported;
        emit TokenSupportUpdated(token, supported);
    }

    function setPaused(bool value) external onlyOwner {
        paused = value;
        emit PauseUpdated(value);
    }

    function domainSeparator() public view returns (bytes32) {
        return keccak256(
            abi.encode(
                DOMAIN_TYPEHASH,
                NAME_HASH,
                VERSION_HASH,
                block.chainid,
                address(this)
            )
        );
    }

    function paymentDigest(
        address payer,
        address token,
        address recipient,
        uint256 amount,
        bytes32 requestId,
        uint256 deadline
    ) public view returns (bytes32) {
        bytes32 structHash = keccak256(
            abi.encode(PAYMENT_TYPEHASH, payer, token, recipient, amount, requestId, deadline)
        );
        return keccak256(abi.encodePacked("\x19\x01", domainSeparator(), structHash));
    }

    /// @notice Execute a payer-signed payment. Only the configured gateway executor may relay it.
    /// @param payer Account whose ERC-20 balance and allowance are used.
    /// @param token Allowlisted ERC-20 token.
    /// @param recipient Exact recipient signed by payer.
    /// @param amount Exact token base-unit amount signed by payer.
    /// @param requestId Unique request identifier, single-use per payer.
    /// @param deadline Unix timestamp after which execution is forbidden.
    /// @param signature 65-byte ECDSA signature over the EIP-712 payment digest.
    function executePayment(
        address payer,
        address token,
        address recipient,
        uint256 amount,
        bytes32 requestId,
        uint256 deadline,
        bytes calldata signature
    ) external nonReentrant {
        if (msg.sender != executor) revert Unauthorized();
        if (paused) revert Unauthorized();
        if (block.chainid != expectedChainId) revert InvalidChain(block.chainid, expectedChainId);
        if (!supportedTokens[token]) revert UnsupportedToken(token);
        if (payer == address(0) || recipient == address(0) || recipient == address(this)) {
            revert InvalidRecipient();
        }
        if (amount == 0 || requestId == bytes32(0)) revert InvalidAmount();
        if (block.timestamp > deadline) revert Expired(deadline);
        if (usedRequestIds[payer][requestId]) revert RequestAlreadyUsed(payer, requestId);

        bytes32 digest = paymentDigest(payer, token, recipient, amount, requestId, deadline);
        if (_recover(digest, signature) != payer) revert InvalidSignature();

        // Effects before interaction. Any failed token transfer reverts this state change too.
        usedRequestIds[payer][requestId] = true;
        _safeTransferFrom(token, payer, recipient, amount);

        emit PaymentExecuted(payer, token, recipient, amount, requestId);
    }

    function _recover(bytes32 digest, bytes calldata signature) private pure returns (address signer) {
        if (signature.length != 65) revert InvalidSignature();
        bytes32 r;
        bytes32 s;
        uint8 v;
        assembly {
            r := calldataload(signature.offset)
            s := calldataload(add(signature.offset, 32))
            v := byte(0, calldataload(add(signature.offset, 64)))
        }
        if (uint256(s) > SECP256K1_HALF_N || (v != 27 && v != 28)) revert InvalidSignature();
        signer = ecrecover(digest, v, r, s);
        if (signer == address(0)) revert InvalidSignature();
    }

    function _safeTransferFrom(address token, address from, address to, uint256 amount) private {
        (bool success, bytes memory returndata) = token.call(
            abi.encodeWithSelector(bytes4(0x23b872dd), from, to, amount)
        );
        if (!success || (returndata.length != 0 && (returndata.length < 32 || !abi.decode(returndata, (bool))))) {
            revert TokenTransferFailed();
        }
    }
}
