import json
from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException, status
from haystack import Pipeline
import base64
from motor.motor_asyncio import AsyncIOMotorDatabase
from app.external import (
 FA_AUTH_DB,
 FA_PERSONALIZATION_COLLECTION, 
 FA_CUSTOMER_COLLECTION,
 BODY_GRAM_BUCKET,
 GroqLLM, 
 merge_collections,
 verify_jwt_token
)
import boto3
from app.main import app
from app.external.llm.prompt import *


router = APIRouter()
S3 = boto3.client("s3")

@router.post("/facial-attributes", status_code=status.HTTP_200_OK)
async def generateFacialAttributes(
    user_data: dict = Depends(verify_jwt_token),
    fa_db: AsyncIOMotorDatabase = Depends(lambda: app.state.fa_db),
    llm_client: GroqLLM = Depends(lambda: app.state.llm_client),
    ):
    
    user_id = user_data["id"]
    # print(fa_db)
    db = fa_db[FA_AUTH_DB]
    user_data = await merge_collections(db[FA_CUSTOMER_COLLECTION],db[FA_PERSONALIZATION_COLLECTION],"_id","customer",ObjectId(user_id))
    front_image = S3.get_object(
            Bucket=BODY_GRAM_BUCKET, Key=user_data["facePhoto"]
        )["Body"].read()

    front_photo_base64 = base64.b64encode(front_image).decode()

    user_prompt = [{
            "role": "user",
            "content": [
                {
                    "type": "text",
                    "text": "Extract the facial features from this image"
                },
                {
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:image/jpeg;base64,{front_photo_base64}"
                    }
                }
            ]
        }]
    
    count = 1
    while count <= 5:
        extracted_facial_attrs = await llm_client.chat(
            Facial_attrs_prompt + user_prompt )
        extracted_facial_attrs = json.loads(extracted_facial_attrs)
        extracted_facial_attrs = [f"{key}={value}" for key, value in extracted_facial_attrs.items()]
        result = await db[FA_PERSONALIZATION_COLLECTION].update_one(
            {"_id": user_data["_id"]},
            {"$set": {"facial_attrs": extracted_facial_attrs}}
        )

        if result.modified_count:
            return {"message": "Facial attributes updated successfully"}
        else:
            count += 1
    raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Unable to generate facial attributes"
        )