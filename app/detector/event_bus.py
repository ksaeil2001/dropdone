import queue
import threading
import uuid
from datetime import datetime
from typing import Callable

from app.utils.scheduler import KeyedDelayScheduler


class EventBus:
    _settle_window_sec = 0.9
    _recent_dedupe_window_sec = 0.5
    _scheduler = KeyedDelayScheduler('event-bus-delay')

    def __init__(self):
        self._subscribers: list[Callable] = []
        self._sse_queues: list[queue.Queue] = []
        self._sse_lock = threading.Lock()
        self._event_lock = threading.Lock()
        self._pending_events: dict[str, dict] = {}
        self._recent_events: dict[str, float] = {}

    def subscribe(self, handler: Callable):
        self._subscribers.append(handler)

    def add_sse_client(self, q: queue.Queue):
        with self._sse_lock:
            self._sse_queues.append(q)

    def remove_sse_client(self, q: queue.Queue):
        with self._sse_lock:
            try:
                self._sse_queues.remove(q)
            except ValueError:
                pass

    def _dedupe_key(self, data: dict) -> str:
        path = (data.get('path') or '').strip().lower()
        size = int(data.get('size') or 0)
        if path:
            return f'{path}|{size}'

        filename = (data.get('filename') or '').strip().lower()
        session_id = (data.get('session_id') or '').strip().lower()
        if filename or session_id:
            return f'{filename}|{session_id}|{size}'
        return ''

    def _recent_key(self, data: dict, dedupe_key: str) -> str:
        source = (data.get('source') or '').strip().lower()
        detector = (data.get('detector') or '').strip().lower()
        return f'{dedupe_key}|{source}|{detector}'

    def _event_priority(self, data: dict) -> int:
        detector = (data.get('detector') or '').strip().lower()
        source = (data.get('source') or '').strip().lower()

        detector_priority = {
            'chrome_extension': 50,
            'chrome_detector': 50,
            'mega_fs': 40,
            'hitomi_fs': 40,
            'browser_fs': 10,
            'hdd_fs': 10,
        }
        source_priority = {
            'chrome': 50,
            'mega': 40,
            'app': 40,
            'browser': 10,
            'hdd': 10,
        }
        return max(detector_priority.get(detector, 0), source_priority.get(source, 0))

    def _merge_pending_event(self, existing: dict, incoming: dict) -> None:
        if self._event_priority(incoming) > self._event_priority(existing):
            for field in ('source', 'detector', 'mime', 'final_url', 'session_id'):
                value = incoming.get(field)
                if value not in (None, ''):
                    existing[field] = value
        else:
            for field in ('mime', 'final_url', 'session_id'):
                value = incoming.get(field)
                if value not in (None, '') and not existing.get(field):
                    existing[field] = value

        for field in ('path', 'filename'):
            value = incoming.get(field)
            if value and not existing.get(field):
                existing[field] = value

        incoming_size = incoming.get('size')
        if incoming_size not in (None, '') and not existing.get('size'):
            existing['size'] = incoming_size

    def _prune_recent_locked(self, now_ts: float):
        expired = [
            key for key, seen_at in self._recent_events.items()
            if now_ts - seen_at > self._recent_dedupe_window_sec
        ]
        for key in expired:
            del self._recent_events[key]

    def _dispatch(self, data: dict):
        for handler in self._subscribers:
            try:
                handler(data)
            except Exception:
                pass

        payload = _json_dumps(data)
        with self._sse_lock:
            dead = []
            for q in self._sse_queues:
                try:
                    q.put_nowait(payload)
                except queue.Full:
                    dead.append(q)
            for q in dead:
                self._sse_queues.remove(q)

    def publish(self, data: dict):
        import time as _time

        now = _time.monotonic()
        dedupe_key = self._dedupe_key(data)

        if not data.get('id'):
            data = dict(data)
            data['id'] = str(uuid.uuid4())
        if not data.get('timestamp'):
            data = dict(data)
            data['timestamp'] = datetime.now().isoformat(timespec='seconds')

        with self._event_lock:
            self._prune_recent_locked(now)

            # ── 동일 source 단기 중복 억제 (0.5초 창) ───────────────────────
            if dedupe_key:
                recent_key = self._recent_key(data, dedupe_key)
                if recent_key in self._recent_events:
                    return
                self._recent_events[recent_key] = now

            # ── settle window: 이미 대기 중이면 정보 보강만 ─────────────────
            if dedupe_key and dedupe_key in self._pending_events:
                existing = self._pending_events[dedupe_key]
                self._merge_pending_event(existing, data)
                return

            # ── 새 이벤트: KeyedDelayScheduler로 settle 등록 ────────────────
            captured = dict(data)

            if dedupe_key:
                self._pending_events[dedupe_key] = captured

                def _fire(key=dedupe_key, d=captured):
                    with self._event_lock:
                        self._pending_events.pop(key, None)
                    self._dispatch(d)

                self._scheduler.schedule(dedupe_key, self._settle_window_sec, _fire)
            else:
                threading.Thread(target=self._dispatch, args=(captured,), daemon=True).start()


def _json_dumps(obj) -> str:
    import json
    return json.dumps(obj, ensure_ascii=False, default=str)
