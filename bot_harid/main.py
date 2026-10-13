"""Run the selected feature through the shared durable runtime."""

from services.runtime import entrypoint, run


async def main():
    await run(("harid",))


if __name__ == "__main__":
    entrypoint(("harid",))
