import logging
import os
from contextlib import AsyncExitStack, asynccontextmanager
from functools import partial

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.api import router
from app.config import settings
from app.db.database import SessionLocal
from app.db.migrations import run_migrations
from app.events.handlers import handle_order_event
from app.events.runtime import kafka_runtime
from app.events.schemas import ORDERS_TOPIC
from app.gateway import MockPaymentGateway, PaymentGateway
from app.repository import PostgresRepository, Repository
from app.service import Declined, PaymentError, PaymentService

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s [%(name)s] %(message)s")


@asynccontextmanager
async def lifespan(app: FastAPI):
    if settings.RUN_MIGRATIONS:
        run_migrations()
    async with AsyncExitStack() as stack:
        if settings.KAFKA_ENABLED:
            await stack.enter_async_context(kafka_runtime(
                consume_topic=ORDERS_TOPIC,
                group_id="payment-service",
                handler=partial(handle_order_event, app.state.payment_service, SessionLocal),
                session_factory=SessionLocal,
            ))
        yield

def create_app(
    gateway: PaymentGateway | None = None, repository: Repository | None = None
) -> FastAPI:
    app = FastAPI(title="Payment Service", version="0.1.0", lifespan=lifespan)

    if gateway is None:
        latency = float(os.getenv("MOCK_GATEWAY_LATENCY_SECONDS", "0"))
        gateway = MockPaymentGateway(latency_seconds=latency)
    if repository is None:
        repository = PostgresRepository(SessionLocal)
    app.state.payment_service = PaymentService(repository, gateway)

    @app.exception_handler(PaymentError)
    def handle_payment_error(_: Request, exc: PaymentError) -> JSONResponse:
        content = {"error": exc.code, "message": exc.message}
        if isinstance(exc, Declined) and exc.resource_id:
            content["resource_id"] = exc.resource_id
        return JSONResponse(status_code=exc.status_code, content=content)

    @app.get("/health", tags=["health"])
    def health() -> dict[str, str]:
        return {"status": "ok"}

    app.include_router(router)
    return app


app = create_app()