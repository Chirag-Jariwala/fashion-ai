import json
import httpx
from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException, status
from haystack import Pipeline
from motor.motor_asyncio import AsyncIOMotorDatabase
from redis import Redis
from types import SimpleNamespace
import re
from app.external import FA_CUSTOMER_COLLECTION,FA_AUTH_DB, FA_PERSONALIZATION_COLLECTION, FA_PRODUCT_COLLECTION, FA_WARDROBE_PAIR_COLLECTION ,FA_AI_DB, GroqLLM, merge_collections, verify_jwt_token
from app.main import app
from app.models import WardrobeReasoner, UserAttrs, AIStyleReasoner, ProductDetails
from app.external.llm.prompt import *
from app.api.ai_search import ai_search

router = APIRouter()

def convert_height_to_mm(height_str):
    match = re.match(r"(\d+)'[\s]*(\d+)?", height_str)
    if match:
        feet = int(match.group(1))
        inches = int(match.group(2) or 0)
        mm = round((feet * 304.8) + (inches * 25.4))
        return mm
    return 500

def convert_weight_to_grams(weight_str):
    match = re.search(r"[\d.]+", weight_str)
    if match:
        grams = float(match.group()) * 1000
        return int(round(grams))
    return 10000

async def merge_product_details(
        product_id: str, db: AsyncIOMotorDatabase
):
    collection =  db[FA_AI_DB][FA_PRODUCT_COLLECTION]
    pascursor = collection.find({"product_id": ObjectId(product_id)})
    results = []
    async for document in pascursor:
        if not results:
            results.append(document)
        else:
            if not results[0].get("colors"):
                results[0]["colors"] = document["colors"]
            # elif not results[0].get("styles"):
                # results[0]["styles"] = document["styles"]
            else:
                results[0]["colors"].extend(document["colors"])
                # results[0]["styles"].append(document["styles"])
    return results[0]

async def fetch_user_attrs(
    user_id: str, db: AsyncIOMotorDatabase
) -> str:
    Customer_collection = db[FA_AUTH_DB][FA_CUSTOMER_COLLECTION]
    personalization_collection = db[FA_AUTH_DB][FA_PERSONALIZATION_COLLECTION]
    user_attrs = await merge_collections(Customer_collection,personalization_collection,"_id","customer",ObjectId(user_id))
    if not user_attrs:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="User not found"
        )
    user_attrs = {
            "user_id": user_attrs["_id"],
            "skin_color" : user_attrs.get("skin_color"),
            "height": convert_height_to_mm(user_attrs["height"]),
            "weight" : convert_weight_to_grams(user_attrs["weight"]),
            "age" : user_attrs.get("age"),
            "facial_attrs" : user_attrs.get("facial_attrs",[]),
            "physical_attrs" : user_attrs.get("physical_attrs",[])
        }
    return UserAttrs(**user_attrs).to_str()

def paginate_documents(redis, cache_key, results=[], page=1, page_size=10):
    """
    Paginate through the retrieved documents.

    """
    start = (page - 1) * page_size
    end = start + page_size
    if not results:
        cached_results = redis.get(cache_key)
        if cached_results:
            results = json.loads(str(cached_results))
            if not results:
                return []
            return results[start:end] if len(results) > end else results[start:]
    return results[start:end] if len(results) > end else results[start:]

async def fetch_product_details(
    product_id: str, db: AsyncIOMotorDatabase
) -> str:
    product_details = await merge_product_details(product_id,db)
    if not product_details:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="product not found"
        )
    product_details = {
        "_id": ObjectId(product_details["product_id"]),
        "name": product_details["productName"],
        "description": product_details["description"],
        "colors" : product_details["colors"],
        "brand" : product_details["brand"]
    }
    return ProductDetails(**product_details).to_str()

async def fetch_wardrobe_pair(
    user_id: str,product_id: str, db: AsyncIOMotorDatabase
):
    collection = db[FA_AI_DB][FA_WARDROBE_PAIR_COLLECTION]
    product_details = None
    product_details = await collection.find_one(
        {
            "user_id": user_id,
            "product_id": product_id
        },)
    return product_details

async def insert_wardrobe_pair(
    user_id: str, product_id: str, db: AsyncIOMotorDatabase, pair: dict
):
    collection = db[FA_AI_DB][FA_WARDROBE_PAIR_COLLECTION]
    new_recommendation = {
            "user_id": user_id,
            "product_id": product_id,
            "recommendations":pair
        }
    result = collection.insert_one(
        new_recommendation
    )
    return result

async def call_ai_search(user_id,product,token: str):
    url = "http://127.0.0.1:80/ai/v1/search"  # Use correct host and port

    payload = {
        "user_id": user_id,
        "user_query": product[0],
        "include_trendicles": False,
        "page": 1,
        "page_size": 1
    }
    headers = {
            "Authorization": f"Bearer {token}"
        }

    async with httpx.AsyncClient(timeout=60) as client:
        response = await client.post(url, json=payload, headers=headers)
        print(f"Opensearch response {response.json()}")
    return response.json()


@router.post("/wardrobe-recommendation", status_code=status.HTTP_200_OK)
async def wardrobe(
    user_request: WardrobeReasoner,
    user_data: dict = Depends(verify_jwt_token),
    fa_db: AsyncIOMotorDatabase = Depends(lambda: app.state.fa_db),
    llm_client: GroqLLM = Depends(lambda: app.state.llm_client),
    open_search_retriever: Pipeline = Depends(lambda: app.state.open_search_retriever),
    redis: Redis = Depends(lambda: app.state.redis),
):
    user_id = user_data["id"]
    user_token = user_data["token"]
    product_id = user_request.product_id
    available_recommendation = await fetch_wardrobe_pair(user_id, product_id, fa_db)
    if available_recommendation:
        return available_recommendation["recommendations"]
    # Check for cached response first
    cache_key = str(user_request)
    # check for cache if results are already loaded else do a fresh query
    if results := paginate_documents(redis, cache_key, [], user_request.page, user_request.page_size):
        print(f"Cached response found: {cache_key}")
        return {
            "products": results,
            "info": {
                "page": user_request.page,
                "page_size": user_request.page_size,
                "count": len(results),
            },
        }

    user_attrs = await fetch_user_attrs(user_id, fa_db)
    llm_client.system_prompt = WARDROBE_RECOMMENDER_SYSTEM_PROMPT
    product_details = await fetch_product_details(product_id,fa_db)
    llm_query = f"""----------- User Attributes ----------
    {user_attrs}
    Input Product:- {product_details}"""
    while True:
        try:
            core_recommendations = await llm_client.chat(
                WARDROBE_RECOMMENDER_PROMPT + [{"role": "user", "content": llm_query}]
            )
            break
        except:
            continue
    core_recommendations = json.loads(core_recommendations)
    recomended_products = []
    for i in core_recommendations['recommendations']:
        if len(recomended_products) >= 3:
            break
        result = await call_ai_search(user_id,["Lewis T-shirt"],user_token)
        if result.get("products"):
            product_description = result["products"][0]["content"]
            llm_client.system_prompt = WARDROBE_PAIR_MAKING_SYSTEM_PROMPT
            llm_query = f"""----------- User Attributes ----------
            {user_attrs}
            Input Product1:- {product_details}
            Input Product2:- {product_description}"""
            while True:
                try:    
                    core_recommendations = await llm_client.chat(
                        WARDROBE_PAIR_MAKING_PROMPT + [{"role": "user", "content": llm_query}]
                    )
                    break
                except Exception as e:
                    continue
            core_recommendations = json.loads(core_recommendations)
            core_recommendations["product_details"] = result["products"][0]
            recomended_products.append(core_recommendations)
        else:
            pass
    if recomended_products:
        update_recommendation = await insert_wardrobe_pair(user_id, product_id, fa_db, recomended_products)
        redis.set(cache_key, json.dumps(recomended_products), ex=300)  # Cache for 1 hour

    return recomended_products