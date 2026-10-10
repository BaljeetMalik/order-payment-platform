from sqlalchemy.orm import Session

from app.db.tables import Outbox
from app.events.schemas import Event


def add_event(session: Session, topic: str, event: Event) -> None:
    """Stage an event in the outbox. The caller commits, so the event is saved
    in the same transaction as the business change."""
    outbox_event = Outbox(
        event_id=event.event_id,
        topic=topic,
        key=str(event.order_id),
        payload=event.model_dump(mode="json"),
    )
    session.add(outbox_event)
