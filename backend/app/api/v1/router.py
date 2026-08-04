"""Aggregates every v1 route module.

Later phases register their routers here: auth (2), documents (3), search (6),
chat (7), dashboard (8), repositories (9).
"""

from fastapi import APIRouter

from app.api.v1.routes import auth, documents, health, system

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(system.router)
api_router.include_router(auth.router)
api_router.include_router(documents.router)
