import uuid
from datetime import datetime
from typing import Callable


class EventBus:
    def __init__(self):
        self._subscribers: list[Callable] = []

    def subscribe(self, handler: Callable):
        self._subscribers.append(handler)

    def publish(self, data: dict):
        event = {
            'id':         data.get('id', str(uuid.uuid4())),
            'source':     data.get('source', ''),
            'filename':   data.get('filename', ''),
            'path':       data.get('path', ''),
            'size':       data.get('size', 0),
            'mime':       data.get('mime', ''),
            'timestamp':  data.get('timestamp', datetime.now().isoformat()),
            'session_id': data.get('session_id', None),
            'batch_total':data.get('batch_total', None),
        }
        for handler in self._subscribers:
            try:
                handler(event)
            except Exception as e:
                print(f'[EventBus] handler error: {e}')
