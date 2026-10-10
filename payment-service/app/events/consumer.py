import asyncio
import logging
from collections.abc import Callable

from aiokafka import AIOKafkaConsumer, AIOKafkaProducer
from pydantic import ValidationError

from app.config import settings
from app.events.schemas import Event

log = logging.getLogger(__name__)

Handler = Callable[[Event], None]

async def run_consumer(
        topic: str,
        group_id: str,
        handler: Handler,
        producer: AIOKafkaProducer,
        max_attempts: int = 3,
) -> None:
    consumer = AIOKafkaConsumer(
        topic,
        group_id=group_id,
        bootstrap_servers=settings.KAFKA_BOOTSTRAP_SERVERS,
        enable_auto_commit=False,
        auto_offset_reset="earliest",
    )
    await consumer.start()
    try:
        async for msg in consumer:
            await _process(msg, handler, producer, max_attempts)
            await consumer.commit()
    finally:
        await consumer.stop()


async def _process(msg, handler: Handler, producer: AIOKafkaProducer, max_attempts: int) -> None:
    dlq_topic = f"{msg.topic}.dlq"
    try:
        event = Event.model_validate_json(msg.value)
    except ValidationError:
        log.exception("unparseable message on %s offset=%s; sending to %s", msg.topic, msg.offset, dlq_topic)
        await producer.send_and_wait(dlq_topic, key=msg.key, value=msg.value)
        return

    for attempt in range(1, max_attempts+1):
        try:
            await asyncio.to_thread(handler, event)
            return
        except Exception:
            log.exception("handler failed %s order_id=%s event_id=%s attempt=%s/%s",
                          event.event_type, event.order_id, event.event_id, attempt, max_attempts)
            if attempt < max_attempts:
                await asyncio.sleep(2 ** attempt)

    log.error("handler failed after %s attempts, sending to %s", max_attempts, dlq_topic)
    await producer.send_and_wait(dlq_topic, key=msg.key, value=msg.value)
    