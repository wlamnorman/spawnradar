from fastapi import APIRouter
from fastapi.responses import JSONResponse

router = APIRouter()


@router.get("/healthz")
async def health() -> JSONResponse:
    return JSONResponse({"status": "ok"})
