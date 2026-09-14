from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    yield


app = FastAPI(lifespan=lifespan)


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


if __name__ == "__main__":
    # workers=1: rooms are in-memory, owned by one process. docs/07-infra.md §2
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, workers=1)
