import argparse
import asyncio
import json
import os
from dataclasses import asdict

import uvicorn

from isee.app import create_app
from isee.config import RouterSettings, load_settings
from isee.logging_config import configure_logging
from isee_network.routeros import RouterOSRestClient, RouterOSError, RouterSnapshot


def main() -> None:
    parser = argparse.ArgumentParser(prog="isee")
    commands = parser.add_subparsers(dest="command")
    router_command = commands.add_parser("router", help="RouterOS diagnostics")
    router_actions = router_command.add_subparsers(dest="router_action", required=True)
    router_actions.add_parser("discover", help="Read RouterOS system and interface information")
    arguments = parser.parse_args()

    settings = load_settings()
    configure_logging(settings.logging.level)

    if arguments.command == "router":
        if settings.router is None:
            parser.error("Configure the [router] section before running router discovery")
        password = os.environ.get("ISEE_ROUTER_PASSWORD")
        if not password:
            parser.error("Set the ISEE_ROUTER_PASSWORD environment variable")
        try:
            snapshot = asyncio.run(_discover_router(settings.router, password))
        except RouterOSError as exc:
            parser.exit(status=1, message=f"Router discovery failed: {exc}\n")
        print(json.dumps(asdict(snapshot), indent=2))
        return

    uvicorn.run(
        create_app(settings),
        host=settings.server.host,
        port=settings.server.port,
        log_config=None,
    )


async def _discover_router(settings: RouterSettings, password: str) -> RouterSnapshot:
    async with RouterOSRestClient(settings, password) as router:
        return await router.discover()
