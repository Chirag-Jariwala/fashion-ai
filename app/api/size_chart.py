import json
from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException, status
from haystack import Pipeline
import base64
from motor.motor_asyncio import AsyncIOMotorDatabase
from app.external import (
 FA_PRODUCT_DB,
 FA_PRODUCT_COLLECTION,
 BODY_GRAM_BUCKET,
 GroqLLM, 
 merge_collections
)
import boto3
from app.main import app
from app.models import SizeChart
from app.external.llm.prompt import *


router = APIRouter()
S3 = boto3.client("s3")

@router.post("/get-size-chart", status_code=status.HTTP_200_OK)
async def generateSizeChart(
    user_request: SizeChart,
    fa_db: AsyncIOMotorDatabase = Depends(lambda: app.state.fa_db),
    llm_client: GroqLLM = Depends(lambda: app.state.llm_client),
    ):
    
    product_id = user_request.product_id
    collection = fa_db[FA_PRODUCT_DB][FA_PRODUCT_COLLECTION]
    document = await collection.find_one({"_id": ObjectId(product_id)})
    if not document or "sizeChartMedia" not in document:
        raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Could not find any product or SizeChart for provided product id"
            )
    
    size_chart = S3.get_object(
            Bucket=BODY_GRAM_BUCKET, Key=document["sizeChartMedia"]
        )["Body"].read()

    size_chart_base64 = base64.b64encode(size_chart).decode()

    user_prompt = [{
            "role": "user",
            "content": [
                {
                    "type": "text",
                    "text": "extract size chart information from this image"
                },
                {
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:image/jpeg;base64,{size_chart_base64}"
                    }
                }
            ]
        }]
    
    count = 1
    # print(Facial_attrs_prompt + user_prompt)
    while count <= 5:
        try:
            extracted_size_chart = await llm_client.chat(
                SIZE_CHART_PROMPT + user_prompt )
            extracted_size_chart = json.loads(extracted_size_chart)
            if not extracted_size_chart.get("size_chart",None):
                raise Exception("Could not find any SizeChart Information")
            
            result = await collection.update_one(
                {"_id": document["_id"]},
                {"$set": {"SizeChart": extracted_size_chart["size_chart"]}}
            )

            if result.modified_count:
                return {"message": "Size Chart updated successfully"}
            else:
                count += 1
        except Exception as e:
            count += 1
            print(e)

    raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Could not extract size chart details from image"
        )
