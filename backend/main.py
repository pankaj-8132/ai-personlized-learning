from pathlib import Path
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from .db import init_db
from .routers import auth_routes, document_routes, learning_routes

app = FastAPI(title="LearnLoop")
init_db()
app.include_router(auth_routes.router)
app.include_router(document_routes.router)
app.include_router(learning_routes.router)
app.mount("/", StaticFiles(directory=Path(__file__).parent.parent / "frontend", html=True), name="ui")
