import logging
import os

from dotenv import load_dotenv
from pymongo import AsyncMongoClient
from pymongo.errors import ConnectionFailure
from pymongo.server_api import ServerApi

logger = logging.getLogger(__name__)
load_dotenv()

# One client is shared by every request (see app.app_lifespan), so these bound
# what the whole server can have in flight at once, not what one caller gets.
#
# minPoolSize pre-warms connections: the pool otherwise starts empty and the
# first burst of concurrent requests each pays a TCP + TLS + auth handshake
# before its query begins.
MIN_POOL_SIZE = 5
# The pymongo default, set explicitly because it is the server's real
# concurrency ceiling: request 101 waits for a connection regardless of how
# idle the event loop is.
MAX_POOL_SIZE = 100
# Unset by default, which means a pool-exhaustion event queues forever. A
# bounded wait turns that into an error the caller can see.
WAIT_QUEUE_TIMEOUT_MS = 5_000
# Down from the 30s default. A hung request holds its MCP session open, so
# failing fast keeps an unreachable database from parking every concurrent
# caller. Still comfortably longer than a replica-set election, so a routine
# Atlas failover rides through rather than erroring.
SERVER_SELECTION_TIMEOUT_MS = 10_000


async def create_mongodb_client() -> AsyncMongoClient:

    db_uri = os.getenv("DB_URI")
    if not db_uri:
        logger.error("DB_URI environment variable is not set")
        raise ValueError("DB_URI environment variable is not set")
    else:
        logger.info("DB_URI environment variable is set")

    client: AsyncMongoClient = AsyncMongoClient(
        db_uri,
        server_api=ServerApi("1"),
        minPoolSize=MIN_POOL_SIZE,
        maxPoolSize=MAX_POOL_SIZE,
        waitQueueTimeoutMS=WAIT_QUEUE_TIMEOUT_MS,
        serverSelectionTimeoutMS=SERVER_SELECTION_TIMEOUT_MS,
    )

    # The client owns a connection pool and background topology-monitoring
    # tasks from the moment it is constructed, not from the first query. A ping
    # that fails therefore has to shut it down: raising on its own would leave
    # those tasks running with nothing holding a reference to close them. Both
    # arms close, including the re-raise, because a cancellation here leaks
    # exactly as much as a refused connection does.
    try:
        await client.admin.command("ping")
    except ConnectionFailure as e:
        await client.close()
        logger.error(f"Failed to connect to MongoDB {e}")
        raise ConnectionError("Failed to connect to MongoDB") from e
    except BaseException:
        await client.close()
        raise

    logger.info("Pinged your deployment. You successfully connected to MongoDB!")
    return client
