"""Run the selected feature through the shared durable runtime."""

from services.runtime import entrypoint, run


async def main():
    await run(("harajat",))


if __name__ == "__main__":
    entrypoint(("harajat",))
