import logging
import os

from dotenv import load_dotenv
from pymongo import MongoClient
from pymongo.errors import ConnectionFailure
from pymongo.server_api import ServerApi

logger = logging.getLogger(__name__)
load_dotenv()


def create_mongodb_client() -> MongoClient:

    db_password = os.getenv("DB_PASSWORD")
    if not db_password:
        logger.error("DB_PASSWORD environment variable is not set")
        raise ValueError("DB_PASSWORD environment variable is not set")
    else:
        logger.info("DB_PASSWORD environment variable is set")

    uri = f"mongodb+srv://cm_dev:{db_password}@pokemon-tcg-cluster.ufxy8d9.mongodb.net/?appName=pokemon-tcg-cluster"

    client: MongoClient = MongoClient(uri, server_api=ServerApi("1"))

    try:
        client.admin.command("ping")
        logger.info("Pinged your deployment. You successfully connected to MongoDB!")
        return client
    except ConnectionFailure as e:
        logger.error(f"Failed to connect to MongoDB {e}")
        raise ConnectionError("Failed to connect to MongoDB") from e
