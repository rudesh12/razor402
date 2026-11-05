"""scripts/prod.py — Production launcher for cloud deployments (Render, Railway, Fly.io).

Runs database seed, generates ephemeral fallback keys if missing, starts the
upstream merchant on internal 127.0.0.1:9000, and runs the public Razor402
Gateway on the platform's allocated $PORT.
"""
import os
import sys
import subprocess
import signal

# Ensure project root is on sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _ensure_keys():
    """Ensure signing keys exist in environment; generate ephemeral keys if missing."""
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    for key_name in ("GW_SK_HEX", "AGENT_A_SK_HEX", "AGENT_B_SK_HEX"):
        if not os.environ.get(key_name):
            sk = Ed25519PrivateKey.generate().private_bytes_raw().hex()
            os.environ[key_name] = sk
            print(f"[prod] Generated fallback {key_name}")

    if not os.environ.get("RZP_MODE"):
        os.environ["RZP_MODE"] = "harness"


def main():
    _ensure_keys()

    # 1. Initialize DB and seed mandates
    print("[prod] Initializing database and seeding mandates...")
    try:
        from scripts.seed import main as seed_main
        seed_main()
    except Exception as e:
        print(f"[prod] Seed warning (continuing): {e}")

    # 2. Launch upstream merchant mock on internal port 9000
    print("[prod] Launching upstream merchant on 127.0.0.1:9000...")
    merchant_proc = subprocess.Popen([
        sys.executable, "-m", "uvicorn", "merchant.app:app",
        "--host", "127.0.0.1",
        "--port", "9000",
        "--log-level", "warning",
    ])

    # 3. Launch gateway on $PORT (defaults to 8000 locally, 10000 on Render)
    port = int(os.environ.get("PORT", "8000"))
    print(f"[prod] Launching Razor402 Gateway on 0.0.0.0:{port}...")

    def handle_signal(sig, frame):
        print(f"\n[prod] Shutting down services (signal {sig})...")
        merchant_proc.terminate()
        sys.exit(0)

    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    try:
        subprocess.run([
            sys.executable, "-m", "uvicorn", "gateway.app:app",
            "--host", "0.0.0.0",
            "--port", str(port),
        ], check=True)
    finally:
        merchant_proc.terminate()
        try:
            merchant_proc.wait(timeout=3)
        except Exception:
            merchant_proc.kill()


if __name__ == "__main__":
    main()
