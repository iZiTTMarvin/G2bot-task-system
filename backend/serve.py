"""Bind the delivery-mode port before starting application recovery."""
from __future__ import annotations

import os
import socket
import subprocess
import sys
from pathlib import Path

import uvicorn


def main() -> int:
    try:
        port = int(os.environ.get("G2_PORT", "8000"))
        if not 1 <= port <= 65535:
            raise ValueError
    except ValueError:
        print("G2_PORT must be an integer between 1 and 65535.", file=sys.stderr)
        return 1

    host = "127.0.0.1"
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        if os.name == "nt":
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        else:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind((host, port))
        except OSError as exc:
            print(f"Cannot bind {host}:{port}: {exc}", file=sys.stderr)
            return 1

        frontend = Path(__file__).resolve().parents[1] / "frontend"
        command = ["cmd.exe", "/d", "/c", "npm", "run", "build"] if os.name == "nt" else ["npm", "run", "build"]
        print("[3/3] Building frontend...", flush=True)
        if subprocess.run(command, cwd=frontend, check=False).returncode != 0:
            print("Frontend build failed.", file=sys.stderr)
            return 1

        config = uvicorn.Config("app.main:app", host=host, port=port)
        server = uvicorn.Server(config)
        server.run(sockets=[sock])
        return 0 if server.started else 1


if __name__ == "__main__":
    raise SystemExit(main())
