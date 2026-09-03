"""Generate Ed25519 keypairs for .env configuration."""
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey


def main():
    print("# Razor402 Key Generation")
    print("# Paste these into your .env file\n")
    for name in ("GW_SK_HEX", "AGENT_A_SK_HEX", "AGENT_B_SK_HEX"):
        sk = Ed25519PrivateKey.generate()
        raw = sk.private_bytes_raw()
        print(f"{name}={raw.hex()}")
    print("\n# Keys generated. Keep them secret.")


if __name__ == "__main__":
    main()
