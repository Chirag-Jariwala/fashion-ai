import json

from dotenv import load_dotenv
from fastapi import APIRouter, Depends, HTTPException, status
from langchain.chains import LLMChain
from langchain.prompts import PromptTemplate
from langchain_groq import ChatGroq
from motor.motor_asyncio import AsyncIOMotorDatabase
from redis import Redis

from app.external import FA_PRODUCT_DB, FA_PRODUCT_COLLECTION, BODY_GRAM_SCAN_COLLECTION, FA_AI_DB, GroqLLM, verify_jwt_token
from app.main import app
from app.models import SizeRecommendRequest, SizeChart
from app.api.size_chart import generateSizeChart
from bson import ObjectId

load_dotenv()

router = APIRouter()
# ndb = NeuralDB()


# Define size recommendation prompt template
SIZE_RECOMMEND_TEMPLATE = """
You are a clothing size assistant. I'll provide you the body measurements, size chart of the product, and product name. Based on all these parameters you just have to reply in a single word. That word would be the size of the clothing that would fit on the user.

*Body Measurements* : {measurements}

*Product Name* : {product_title}

*Size Chart* : {size_chart}
"""

# Initialize ChatGroq model
prompt = PromptTemplate(
    input_variables=["measurements", "product_title", "size_chart"],
    template=SIZE_RECOMMEND_TEMPLATE,
)


async def fetch_product_chart(
    product_id: str,
    fa_db: AsyncIOMotorDatabase,
    llm_client: GroqLLM
) -> dict | None:
    try:
        collection = fa_db[FA_PRODUCT_DB][FA_PRODUCT_COLLECTION]

        # Step 1: Validate and check product existence
        validated = SizeChart(product_id=product_id)
        document = await collection.find_one({"_id": ObjectId(validated.product_id)})
        if not document:
            raise HTTPException(
                status_code=404,
                detail="Product not found"
            )

        # Step 2: Return if already has SizeChart
        if "SizeChart" in document and document["SizeChart"]:
            return document["SizeChart"]

        # Step 3: Call generation logic
        await generateSizeChart(
            validated,  # SizeChart Pydantic model
            fa_db=fa_db,
            llm_client=llm_client
        )

        # Step 4: Re-check product after generation
        document = await collection.find_one({"_id": ObjectId(validated.product_id)})
        if "SizeChart" in document and document["SizeChart"]:
            return document["SizeChart"]

        raise HTTPException(
            status_code=404,
            detail="SizeChart not found or could not be generated"
        )

    except HTTPException:
        raise  # re-raise fastapi errors

    except Exception as e:
        print("Error in fetch_product_chart:", e)
        raise HTTPException(
            status_code=500,
            detail="An internal error occurred while fetching the size chart"
        )

async def fetch_user_measurements(
        user_id: str, fa_db: AsyncIOMotorDatabase
)  -> dict | None:
    """Fetch the user's measurements from the database."""
    user_entry = await fa_db[FA_AI_DB][BODY_GRAM_SCAN_COLLECTION].find_one({"user_id": user_id})
    if user_entry.get("scan_result",None):
        return user_entry["scan_result"]["entry"]["measurements"]
    return None

@router.post("/recommended_size", status_code=status.HTTP_200_OK)
async def size_recommend(
    size_recommend_request: SizeRecommendRequest,
    user_data: dict = Depends(verify_jwt_token),
    fa_db: AsyncIOMotorDatabase = Depends(lambda: app.state.fa_db),
    redis: Redis = Depends(lambda: app.state.redis),
    llm_client: GroqLLM = Depends(lambda: app.state.llm_client),
):
    
    user_id = user_data["id"]
    """Get the recommended clothing size based on user measurements and product size chart."""
    llm = ChatGroq(model="llama3-8b-8192", temperature=0.1, stop_sequences=["."])
    chain = LLMChain(llm=llm, prompt=prompt, verbose=True)
    # Check for cached response first
    cache_key = str(size_recommend_request)
    cached_result = redis.get(cache_key)

    if cached_result:
        print(f"Cached response found: {cache_key}")
        return json.loads(str(cached_result))

    # Fetch size chart from the database
    chart = await fetch_product_chart(size_recommend_request.product_id, fa_db,llm_client)
    measurements = await fetch_user_measurements(user_id,fa_db)
    if not chart:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Size chart not found for the given product",
        )

    # Get the recommended size using the LLM chain
    recommended_size = chain.invoke(
        {
            "measurements": measurements,
            "product_title": size_recommend_request.product_title,
            "size_chart": chart,
        }
    )

    # Cache the response on first request
    redis.set(cache_key, json.dumps(recommended_size), ex=10)
    return recommended_size
