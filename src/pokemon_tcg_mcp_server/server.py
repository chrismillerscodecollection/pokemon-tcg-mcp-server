import logging
import os
import sys

from dotenv import load_dotenv

from pokemon_tcg_mcp_server import tools  # noqa: F401  (registers the tools)
from pokemon_tcg_mcp_server.app import mcp

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    stream=sys.stdout,
    format="%(asctime)s %(levelname)s %(message)s",
)


def env_flag(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def main():
    # One uvicorn process, so one event loop on one core. That is the right
    # shape here: the tools are ~1ms of CPU against database round trips an
    # order of magnitude longer, so the loop saturates long after Mongo does.
    #
    # Sessions live in this process's memory by default, which means a second
    # replica behind a load balancer needs sticky routing on 'Mcp-Session-Id'.
    # STATELESS_HTTP=true drops the session store so any replica can serve any
    # request. It is safe for these tools -- all four are request/response and
    # none uses sampling, elicitation, or progress notifications, which are
    # what a stateless transport gives up. Left off by default so the local
    # development posture does not change.
    stateless = env_flag("STATELESS_HTTP")
    if stateless:
        logging.getLogger(__name__).info("Serving in stateless HTTP mode")

    mcp.run(
        transport="http",
        host=os.getenv("HOST", "0.0.0.0"),
        port=int(os.getenv("PORT", "8000")),
        stateless_http=stateless,
    )


if __name__ == "__main__":
    main()
