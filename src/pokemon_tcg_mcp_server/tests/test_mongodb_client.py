import os

from dotenv import load_dotenv
from pymongo import MongoClient
from pymongo.errors import ConnectionFailure
from pymongo.server_api import ServerApi

load_dotenv()

db_password = os.getenv("DB_PASSWORD")
uri = f"mongodb+srv://cm_dev:{db_password}@pokemon-tcg-cluster.ufxy8d9.mongodb.net/?appName=pokemon-tcg-cluster"
client: MongoClient = MongoClient(uri, server_api=ServerApi("1"))


def connect_to_mongodb():
    try:
        client.admin.command("ping")
        print("Pinged your deployment. You successfully connected to MongoDB!")
        return(True)
    except ConnectionFailure as e:
        print(f"Failed to connect to MongoDB: {e}")
        return(False)
    
def test_connect_to_mongodb():
    assert connect_to_mongodb() == True