from sqlalchemy.orm import Session

from .schemas import Event
from app.models.events import Outbox    

def add_event(session: Session, topic:str, event: Event) -> None:
    outbox_event = Outbox(
        event_id=event.event_id,
        topic=topic,
        key=str(event.order_id),
        payload=event.model_dump(mode="json")
    )
    session.add(outbox_event)
    session.commit()

