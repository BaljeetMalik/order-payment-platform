import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from aiokafka import AIOKafkaProducer
from sqlalchemy.orm import Session, sessionmaker

from app.config import settings
from app.events.consumer import Handler, run_consumer
from app.events.relay import run_relay


@asynccontextmanager
async def kafka_runtime(
    consume_topic: str,
    group_id: str,
    handler: Handler,
    session_factory: sessionmaker[Session],
) -> AsyncIterator[None]:
    producer = AIOKafkaProducer(
        bootstrap_servers=settings.KAFKA_BOOTSTRAP_SERVERS,
        acks="all",
        enable_idempotence=True,
    )
    await producer.start()
    tasks = [
        asyncio.create_task(run_relay(producer, session_factory), name="outbox-relay"),
        asyncio.create_task(run_consumer(consume_topic, group_id, handler, producer), name="consumer"),
    ]
    try:
        yield
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await producer.stop()