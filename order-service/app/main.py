import logging
from contextlib import AsyncExitStack, asynccontextmanager
from functools import partial

from fastapi import FastAPI
from app.api.orders import router
from app.config import settings
from app.db.database import SessionLocal
from app.db.migrations import run_migrations
from app.db.seed import seed_sample_data
from app.events.handlers import handle_payment_event
from app.events.runtime import kafka_runtime
from app.events.schemas import PAYMENTS_TOPIC

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s [%(name)s] %(message)s")


@asynccontextmanager
async def lifespan(app: FastAPI):
    if settings.RUN_MIGRATIONS:
        run_migrations()
    if settings.SEED_SAMPLE_DATA:
        seed_sample_data()
    async with AsyncExitStack() as stack:
        if settings.KAFKA_ENABLED:
            await stack.enter_async_context(kafka_runtime(
                consume_topic=PAYMENTS_TOPIC,
                group_id="order-service",
                handler=partial(handle_payment_event, SessionLocal),
                session_factory=SessionLocal,
            ))
        yield


app = FastAPI(lifespan=lifespan)
app.include_router(router)

@app.get("/")
def read_root():
    return {"Hello Dear": "Welcome to Order Service"}

@app.get("/health")
def read_health():
    return {"status": "up"}