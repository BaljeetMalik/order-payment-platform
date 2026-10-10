import asyncio
import json
import logging
from datetime import datetime, timezone

from aiokafka import AIOKafkaProducer
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.models.events import Outbox

log = logging.getLogger(__name__)

async def run_relay(
        producer: AIOKafkaProducer,
        session_factory: sessionmaker[Session],
        idle_interval: float = 0.5,
        error_interval: float = 5.0,
        ) -> None:
    while True:
        try:
            sent = await _publish_batch(producer, session_factory)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            log.exception("Error in relay: %s", e)
            await asyncio.sleep(error_interval)
            continue
        if sent == 0:
            await asyncio.sleep(idle_interval)

async def _publish_batch(producer: AIOKafkaProducer, session_factory: sessionmaker[Session], batch_size: int = 100) -> int:
    with session_factory() as session:
        rows = session.scalars(
            select(Outbox)
            .where(Outbox.published_at.is_(None))
            .order_by(Outbox.id)
            .limit(batch_size)
            .with_for_update(skip_locked=True)
        ).all()

        for row in rows:
            await producer.send_and_wait(
                row.topic, key= row.key.encode("utf-8"), value=json.dumps(row.payload).encode("utf-8")
            )
            row.published_at = datetime.now(timezone.utc)
            log.info("Published message to topic %s with key %s", row.topic, row.key)
        session.commit()
        return len(rows)




