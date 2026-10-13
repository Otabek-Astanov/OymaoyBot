"""Canonical entrypoint for every configured bot token."""

from services.runtime import entrypoint, run

main = run


if __name__ == "__main__":
    entrypoint()
