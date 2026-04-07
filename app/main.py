from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.auth import router as auth_router
from app.friends import router as friends_router
from app.crypto import router as crypto_router
from app.messages import router as messages_router
from app.db import Base, engine

Base.metadata.create_all(bind=engine)

app = FastAPI(title="Secure IM Server")

app.include_router(auth_router)
app.include_router(friends_router)
app.include_router(crypto_router)
app.include_router(messages_router)
app.mount("/static", StaticFiles(directory="app/static"), name="static")


@app.get("/")
def root():
    return {"message": "Server is running"}


@app.get("/ui")
def ui():
    return FileResponse("app/static/index.html")
