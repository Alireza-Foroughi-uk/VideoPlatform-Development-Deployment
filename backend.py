from fastapi import FastAPI, Depends, HTTPException, UploadFile, File
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from passlib.context import CryptContext
import jwt
from azure.cosmos import CosmosClient
from azure.storage.blob import BlobServiceClient
import logging
import json
from typing import Optional

# Initialize FastAPI app
app = FastAPI()

# Configure logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

# Cosmos DB Configuration
COSMOS_URL = "https://alireza-cosmos-db.documents.azure.com:443/"
COSMOS_KEY = "ToxQTfKtm3E4WupgK10FgkB53SPbwPexnsob2duo3KbxIAwOhhtTeWHcfqogsv69pOSCTkXLWpjPACDbxEFd1w=="
DATABASE_NAME = "video_db"
USER_CONTAINER_NAME = "users"
VIDEO_CONTAINER_NAME = "videos"

try:
    client = CosmosClient(COSMOS_URL, credential=COSMOS_KEY)
    database = client.get_database_client(DATABASE_NAME)
    user_container = database.get_container_client(USER_CONTAINER_NAME)
    video_container = database.get_container_client(VIDEO_CONTAINER_NAME)
    logger.info("Connected to Cosmos DB successfully!")
except Exception as e:
    logger.error(f"Failed to connect to Cosmos DB: {str(e)}")
    raise Exception("Failed to initialize Cosmos DB. Check credentials or URL.")

# Blob Storage Connection
BLOB_CONNECTION_STRING = "DefaultEndpointsProtocol=https;AccountName=alirezavideostorage;AccountKey=NVPQKta4uJQVS7fdE261akf/s3wRl8ZR+plO8pxNxv63mc2PBQZ0MzMliLbrSw/MmzAjQNIbD+DV+AStSkcVkA==;EndpointSuffix=core.windows.net"

# OAuth2 and Password Hashing Setup
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

SECRET_KEY = "SECRET_KEY"

# Helper functions
def get_user_from_db(username: str) -> Optional[dict]:
    query = f"SELECT * FROM c WHERE c.username = '{username}'"
    users = list(user_container.query_items(query=query, enable_cross_partition_query=True))
    return users[0] if users else None

def save_user_to_db(username: str, hashed_password: str, role: str = "user"):
    user_data = {
        "id": username,
        "username": username,
        "hashed_password": hashed_password,
        "role": role,
    }
    user_container.upsert_item(user_data)

# Root endpoint
@app.get("/", tags=["General"])
def read_root():
    logger.info("Root endpoint accessed")
    return {"message": "Welcome to the Video Platform API"}

# Signup Endpoint
@app.post("/signup", tags=["Auth"])
def signup(username: str, password: str):
    logger.debug(f"Signup attempt for username: {username}")
    if get_user_from_db(username):
        logger.warning("Signup failed: User already exists")
        raise HTTPException(status_code=400, detail="User already exists")

    hashed_password = pwd_context.hash(password)
    save_user_to_db(username, hashed_password)
    logger.info(f"User {username} signed up successfully")
    return {"message": "User registered successfully"}

# Token Generation and Login
@app.post("/token", tags=["Auth"])
async def login(form_data: OAuth2PasswordRequestForm = Depends()):
    logger.debug("Attempting user login")
    user = get_user_from_db(form_data.username)
    if not user or not pwd_context.verify(form_data.password, user['hashed_password']):
        logger.warning("Invalid login attempt")
        raise HTTPException(status_code=400, detail="Invalid credentials")

    token = jwt.encode({"username": form_data.username, "role": user['role']}, SECRET_KEY, algorithm="HS256")
    logger.info(f"User {form_data.username} logged in successfully")
    return {"access_token": token, "token_type": "bearer"}

# Get Current User
@app.get("/users/me", tags=["Auth"])
async def read_users_me(token: str = Depends(oauth2_scheme)):
    try:
        logger.debug("Fetching current user from token")
        payload = jwt.decode(token, SECRET_KEY, algorithms=["HS256"])
        return payload
    except jwt.ExpiredSignatureError:
        logger.warning("Token expired")
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.InvalidTokenError:
        logger.warning("Invalid token")
        raise HTTPException(status_code=401, detail="Invalid token")

# Upload Video Endpoint
@app.post("/upload", tags=["Upload"])
async def upload_video(file: UploadFile = File(...)):
    try:
        logger.info(f"Uploading video: {file.filename}")
        blob_service = BlobServiceClient.from_connection_string(BLOB_CONNECTION_STRING)
        blob_client = blob_service.get_blob_client(container="videos", blob=file.filename)

        # Upload the video to blob storage
        blob_client.upload_blob(file.file, overwrite=True)
        logger.info(f"Video {file.filename} uploaded to blob storage")

        # Generate video URL
        video_url = f"https://alirezavideostorage.blob.core.windows.net/videos/{file.filename}"

        # Save video metadata to Cosmos DB
        video_metadata = {
            "id": file.filename,
            "title": file.filename.split('.')[0],
            "description": "Uploaded video",
            "url": video_url,
            "uploaded_by": "user1",
            "uploaded_at": "2025-01-11T14:00:00Z",
            "views": 0,
            "likes": 0,
            "dislikes": 0,
            "comments": [],
            "tags": ["uploaded"],
            "category": "Miscellaneous",
        }
        video_container.upsert_item(video_metadata)
        logger.info(f"Video metadata for {file.filename} saved to Cosmos DB")

        return {"message": "Video uploaded successfully", "url": video_url}
    except Exception as e:
        logger.error(f"Upload failed: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Upload failed: {str(e)}")