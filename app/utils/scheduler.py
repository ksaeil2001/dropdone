import heapq
import itertools
import threading
import time
from typing import Callable


class KeyedDelayScheduler:
    def __init__(self, thread_name: str = 'delay-scheduler'):
        self._cv = threading.Condition()
        self._queue: list[tuple[float, int, str, Callable, tuple]] = []
        self._versions: dict[str, int] = {}
        self._counter = itertools.count()
        self._stopped = False
        self._thread = threading.Thread(
            target=self._run,
            daemon=True,
            name=thread_name,
        )
        self._thread.start()

    def schedule(self, key: str, delay: float, func: Callable, *args):
        due_at = time.monotonic() + delay
        version = next(self._counter)
        with self._cv:
            self._versions[key] = version
            heapq.heappush(self._queue, (due_at, version, key, func, args))
            self._cv.notify()

    def cancel(self, key: str):
        with self._cv:
            self._versions.pop(key, None)
            self._cv.notify()

    def shutdown(self):
        with self._cv:
            self._stopped = True
            self._versions.clear()
            self._cv.notify_all()
        self._thread.join(timeout=1)

    def _run(self):
        while True:
            with self._cv:
                while not self._stopped and not self._queue:
                    self._cv.wait()

                if self._stopped:
                    return

                due_at, version, key, func, args = self._queue[0]
                now = time.monotonic()
                if due_at > now:
                    self._cv.wait(due_at - now)
                    continue

                heapq.heappop(self._queue)
                if self._versions.get(key) != version:
                    continue
                self._versions.pop(key, None)

            try:
                func(*args)
            except Exception:
                pass
