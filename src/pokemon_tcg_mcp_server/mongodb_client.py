import logging
import os

from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient
from pymongo.errors import ConnectionFailure
from pymongo.server_api import ServerApi

logger = logging.getLogger(__name__)
load_dotenv()


async def create_mongodb_client() -> AsyncIOMotorClient:

    db_uri = os.getenv("DB_URI")
    if not db_uri:
        logger.error("DB_URI environment variable is not set")
        raise ValueError("DB_URI environment variable is not set")
    else:
        logger.info("DB_URI environment variable is set")

    client: AsyncIOMotorClient = AsyncIOMotorClient(db_uri, server_api=ServerApi("1"))

    try:
        await client.admin.command("ping")
        logger.info("Pinged your deployment. You successfully connected to MongoDB!")
        return client
    except ConnectionFailure as e:
        logger.error(f"Failed to connect to MongoDB {e}")
        raise ConnectionError("Failed to connect to MongoDB") from e
