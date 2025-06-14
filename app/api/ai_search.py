import json
from bson import ObjectId, DBRef
from fastapi import APIRouter, Depends, HTTPException, status
from haystack import Pipeline
from motor.motor_asyncio import AsyncIOMotorDatabase
from haystack.components.embedders import SentenceTransformersTextEmbedder
from redis import Redis
import re
from app.external import (
 FA_AUTH_DB,FA_PRODUCT_DB, 
 FA_CUSTOMER_COLLECTION, 
 FA_PRODUCT_COLLECTION ,
 LOCAL_TRENDICLES_DIR, 
 FA_PERSONALIZATION_COLLECTION, 
 FA_CUSTOMER_COLLECTION,
 FA_PRODUCT_VARIANTS_COLLECTION,
 FA_VARIANTATTRIBUTES_COLLECTION,
 FA_CATEGORY_COLLECTION,
 GroqLLM, 
 verify_jwt_token
)

from app.main import app
from app.models import AISearchRequest, UserAttrs, AIStyleReasoner, ProductDetails, TextEmbeddingResponse, TextEmbeddingRequest
from app.external.llm.prompt import *

router = APIRouter()
# ndb = NeuralDB()


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

async def fetch_customer_with_personalization(db, customer_id: str):
    customer_collection = db[FA_AUTH_DB][FA_CUSTOMER_COLLECTION]
    personalization_collection = db[FA_AUTH_DB][FA_PERSONALIZATION_COLLECTION]

    # Convert string ID to ObjectId
    cust_obj_id = ObjectId(customer_id)

    # Fetch the customer
    customer = await customer_collection.find_one({"_id": cust_obj_id})
    if not customer:
        return None  # Or raise exception if customer not found

    # Fetch the personalization using DBRef $id
    personalization = await personalization_collection.find_one({
        "customer.$id": cust_obj_id
    })

    # Add personalization to customer data
    customer["personalization_data"] = personalization or {}

    return customer

async def fetch_user_attrs(
    user_id: str, db: AsyncIOMotorDatabase, collection_name: str
) -> str:
    # collection = db[collection_name]
    # user_attrs = await collection.find_one({"_id": ObjectId(user_id)})
    
    user_details = await fetch_customer_with_personalization(db,user_id)
    if not user_details:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="User not found"
        )
    
    user_attrs = {
        "user_id": user_details["_id"],
        "skin_color" : user_details["personalization_data"].get("skin_color",None),
        "height": convert_height_to_mm(user_details["personalization_data"]["height"]),
        "weight" : convert_weight_to_grams(user_details["personalization_data"]["weight"]),
        "age" : user_details["personalization_data"]["age"],
        "facial_attrs" : user_details["personalization_data"].get("facial_attrs",[]),
        "physical_attrs" : user_details["personalization_data"].get("physical_attrs",[])
    }
    return UserAttrs(**user_attrs).to_str()

async def fetch_product_details(
    product_id: str, db: AsyncIOMotorDatabase, collection_name: str
) -> str:
    product_id = '67c1cb2f71c0483bcc4f7608'
    product_details = await fetch_combined_product_details(product_id=product_id, db=db)
    if not product_details:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="product not found"
        )
    return ProductDetails(**product_details).to_str()

async def fetch_combined_product_details(
    product_id: str, db: AsyncIOMotorDatabase
):
    product = await db[FA_PRODUCT_DB][FA_PRODUCT_COLLECTION].find_one({"_id": ObjectId(product_id)})
    if not product:
        return {}

    # Category DBRef fix
    category_ref = product.get("category")
    category_id = category_ref.id if isinstance(category_ref, DBRef) else None
    category = await db[FA_PRODUCT_DB][FA_CATEGORY_COLLECTION].find_one({"_id": category_id}) if category_id else {}
    category_name = category.get("name", "")

    # Variants
    variant_ids = [ref.id for ref in product.get("variants", []) if isinstance(ref, DBRef)]
    variants = await db[FA_PRODUCT_DB][FA_PRODUCT_VARIANTS_COLLECTION].find({"_id": {"$in": variant_ids}}).to_list(length=None)

    # VariantAttributes
    attr_ids = [
        attr_ref.id
        for variant in variants
        for attr_ref in variant.get("variantAttributes", [])
        if isinstance(attr_ref, DBRef)
    ]
    attr_docs = await db[FA_PRODUCT_DB][FA_VARIANTATTRIBUTES_COLLECTION].find({"_id": {"$in": attr_ids}}).to_list(length=None)
    attr_map = {a["_id"]: {"attribute": a.get("attribute"), "value": a.get("value")} for a in attr_docs}

    def map_variant(variant):
        attrs = [
            attr_map.get(attr_ref.id, {"attribute": "UNKNOWN", "value": "UNKNOWN"})
            for attr_ref in variant.get("variantAttributes", [])
            if isinstance(attr_ref, DBRef)
        ]
        return {
            "variantId": str(variant["_id"]),
            "name": variant.get("name"),
            "skuCode": variant.get("skuCode"),
            "price": variant.get("price"),
            "inventoryQuantity": variant.get("inventoryQuantity"),
            "externalProductId": variant.get("externalProductId"),
            "externalProductIdType": variant.get("externalProductIdType"),
            "relationshipType": variant.get("relationshipType"),
            "status": variant.get("status"),
            "media": variant.get("media", []),
            "variantAttributes": attrs
        }

    merged_variants = list(map(map_variant, variants))
    colors = {
        attr["value"]
        for variant in merged_variants
        for attr in variant["variantAttributes"]
        if attr["attribute"] == "Color"
    }

    # Handle productType DBRef
    product_type_id = product["productType"].id if isinstance(product.get("productType"), DBRef) else None

    return {
        "productId": str(product["_id"]),
        "name": product.get("productName"),
        "skuCode": product.get("skuCode"),
        "brand": product.get("brand"),
        "description": product.get("description"),
        "categoryName": category_name,
        "manufacturer": product.get("manufacturer"),
        "metadata": product.get("metadata", {}),
        "productTypeId": str(product_type_id) if product_type_id else None,
        "shippingEssentials": product.get("shippingEssentials", {}),
        "approvalStatus": product.get("approvalStatus"),
        "status": product.get("status"),
        "isReturnable": product.get("isReturnable"),
        "isDraft": product.get("isDraft"),
        "colors": list(colors),
        "variants": merged_variants
    }

def fetch_trend_knowledge(query: str) -> str:
    _ndb = ndb.from_checkpoint(LOCAL_TRENDICLES_DIR)
    results = _ndb.search(query, top_k=1)
    trends = "\n".join(result.text for result in results)
    return trends or "No Trend Knowledge"

def build_opensearch_query(open_search_query, user_query, core_categories, top_k_bm25=200):
    user_query_text = open_search_query.get("user_query_with_recommendations", user_query)
    query_data = open_search_query.get("data", {})

    filter_conditions = []

    if core_categories.get("core_categories"):
        filter_conditions.append({
            "field": "categoryId",
            "operator": "in",
            "value": core_categories["core_categories"]
        })

    if brand := query_data.get("brand"):
        filter_conditions.append({
            "field": "brand",
            "operator": "in",
            "value": brand
        })

    for meta_field in ["neckStyle", "careInstruction", "productIdType"]:
        if meta_value := query_data.get(meta_field):
            filter_conditions.append({
                "field": f"metadata.{meta_field}.value",
                "operator": "in",
                "value": meta_value
            })

    filter_conditions.append({
        "field": "variants.inventoryQuantity",
        "operator": ">",
        "value": 0
    })

    search_fields = core_categories.get("weightage", []) + [
        "metadata.neckStyle.value",
        "metadata.careInstruction.value",
        "metadata.productIdType.value",
        "variants.name",
        "variants.variantAttributes.attribute",
        "variants.variantAttributes.value"
    ]

    return {
        "bm25_retriever": {
            "query": user_query_text,
            "scale_score": 1,
            "top_k": top_k_bm25,
            "filters": {
                "operator": "OR",
                "conditions": filter_conditions
            },
            "custom_query": {
                "query": {
                    "bool": {
                        "must": [
                            {
                                "multi_match": {
                                    "query": user_query_text,
                                    "type": "most_fields",
                                    "fields": search_fields
                                }
                            }
                        ]
                    }
                }
            }
        }
    }

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

@router.post("/search", status_code=status.HTTP_200_OK)
async def ai_search(
    user_request: AISearchRequest,
    user_data: dict = Depends(verify_jwt_token),
    fa_db: AsyncIOMotorDatabase = Depends(lambda: app.state.fa_db),
    llm_client: GroqLLM = Depends(lambda: app.state.llm_client),
    open_search_retriever: Pipeline = Depends(lambda: app.state.open_search_retriever),
    redis: Redis = Depends(lambda: app.state.redis),
):
    user_id = user_data["id"]
    user_query = user_request.user_query
    print(f"User id:- {user_id}, User Query:-{user_query}")
    # Check for cached response first
    cache_key = str(user_request)
    # check for cache if results are already loaded else do a fresh query
    if results := paginate_documents(
        redis, cache_key, [], user_request.page, user_request.page_size
    ):
        return {
            "products": results,
            "info": {
                "page": user_request.page,
                "page_size": user_request.page_size,
                "count": len(results),
            },
        }

    # Fetch user attributes from MongoDB
    user_attrs = await fetch_user_attrs(user_id, fa_db, FA_CUSTOMER_COLLECTION)
    # Fetch trend content (optional)
    trends = "No Trend Knowledge"
    if user_request.include_trendicles:
        trends = fetch_trend_knowledge(user_query + user_attrs)
    

    llm_client.system_prompt = AI_SEARCH_CORE_PROMPT
    while True:
        try:
            core_categories = await llm_client.chat(
                AI_SEARCH_CORE_PROMPT + [{"role": "user", "content": user_query}]
            )
            break
        except:
            continue
    core_categories = json.loads(core_categories)

    if core_categories.get("data",{}).get("category",None):
        llm_query = f"""
        {user_attrs}
        Extracted Features: {json.dumps(core_categories)}
        User Query: {user_query}
        """
        llm_client.system_prompt = FEATURE_GENERATOR_PROMPT
        while True:
            try:
                open_search_query = await llm_client.chat(
                    FEATURE_GENERATOR_PROMPT + [{"role": "user", "content": llm_query}]
                    )
                break
            except:
                continue
        open_search_query = json.loads(open_search_query)
        query_payload = build_opensearch_query(open_search_query, user_query, core_categories)
        result = open_search_retriever.run(query_payload)
        documents = result["bm25_retriever"].get("documents", [])
        print(documents)
    else:
        documents = []
    

    # Cache the response on first request
    _results = [doc.to_dict() for doc in documents]
    redis.set(cache_key, json.dumps(_results), ex=300)  # Cache for 1 hour
    results = paginate_documents(
        redis, cache_key, _results, user_request.page, user_request.page_size
    )
    if not results:
        return {"products": []}
        
    return {
        "reasoner": open_search_query["reasoner"],
        "products": sorted(results, key=lambda x: x["score"], reverse=True),
        "info": {
            "page": user_request.page,
            "page_size": user_request.page_size,
            "count": len(results),
        },
    }

@router.post("/style_reasoner", status_code=status.HTTP_200_OK)
async def style_reasoner(
    user_request: AIStyleReasoner,
    user_data: dict = Depends(verify_jwt_token),
    fa_db: AsyncIOMotorDatabase = Depends(lambda: app.state.fa_db),
    llm_client: GroqLLM = Depends(lambda: app.state.llm_client),
    open_search_retriever: Pipeline = Depends(lambda: app.state.open_search_retriever),
    redis: Redis = Depends(lambda: app.state.redis),):
    
    user_id = user_data["id"]
    product_id = user_request.product_id

    if isinstance(product_id,list):
        product_details = await fetch_product_details(product_id[0], fa_db, FA_PRODUCT_COLLECTION)
    else:
        product_details = await fetch_product_details(product_id, fa_db, FA_PRODUCT_COLLECTION)
    user_attrs = await fetch_user_attrs(user_id, fa_db, FA_CUSTOMER_COLLECTION)
    llm_client.system_prompt = STYLE_REASONER_PROMPT
    while True:
        try:
            core_recommendations = await llm_client.chat(
                STYLE_REASONER_PROMPT + [{"role": "user", "content": 
                                        f"""{user_attrs} + "\n\n" + {product_details}"""}],
            )
            break
        except:
            continue
    core_recommendations = json.loads(core_recommendations)
    return {
        "user_id": user_id,
        "Product_id":product_id,
        "Recommendations":core_recommendations["recommendations"]
    }

@router.post("/embed-text", response_model=TextEmbeddingResponse, status_code=status.HTTP_200_OK)
async def embed_text(
    request: TextEmbeddingRequest,
    text_embedder:  SentenceTransformersTextEmbedder = Depends(lambda: app.state.text_embedder),
):
    result = text_embedder.run(request.text)
    return {"embedding": result["embedding"]}