from fastapi import FastAPI

from app.auth import router as auth_router
from app.db import Base, engine
import app.models

Base.metadata.create_all(bind=engine)

app = FastAPI(title="IM Server Auth API")

app.include_router(auth_router)


@app.get("/")
def root():
    return {"message": "Server is running"}