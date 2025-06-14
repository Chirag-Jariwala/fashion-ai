from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase
from pymongo.server_api import ServerApi
from typing import Generator, Dict, List
from ..constants import FA_AUTH_DB, FA_MONGO_URI
from pydantic import PrivateAttr
from pymongo.database import Database


async def get_mongo_connection(uri: str, database_name: str) -> AsyncIOMotorDatabase:
    client = AsyncIOMotorClient(uri, server_api=ServerApi("1"))
    db = client[database_name]
    return db


async def get_fa_connection():
    db_conn = await get_mongo_connection(FA_MONGO_URI, FA_AUTH_DB)
    return db_conn

class MultiMongodb:
    def __init__(self, mongo_uri: str, mongo_db_names: List[str]):
        self.mongo_uri = mongo_uri
        self.mongo_db_names = mongo_db_names
        self._clients = {}

    async def init(self):
        """Initialize MongoDB connections asynchronously."""
        client = AsyncIOMotorClient(self.mongo_uri, server_api=ServerApi("1"))
        self._clients = {db: client[db] for db in self.mongo_db_names}
        return self._clients

    async def get_db(self, db_name: str):
        """Retrieve a database client for the given database name."""
        if db_name not in self._clients:
            raise ValueError(f"Database {db_name} is not configured in MultiMongodb.")
        return self._clients[db_name]
    
async def merge_collections(primary_collection, foreign_collection, primary_key, foreign_key, target_id):    
    primary_doc = await primary_collection.find_one({f"{primary_key}": target_id})
    if not primary_doc:
        return f"No document found with _id = {target_id}"
    print(f"finding id {target_id}")
    foreign_doc = await foreign_collection.find_one({f"{foreign_key}.$id": target_id})
    if foreign_doc:
        merged_doc = {**primary_doc, **foreign_doc}  # Merge the documents
    else:
        merged_doc = None
    
    return merged_doc