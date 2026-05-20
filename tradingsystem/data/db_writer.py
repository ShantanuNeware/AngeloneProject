import threading
import queue
import time
from typing import Callable, Any, Tuple


class DBWriter:
    """A lightweight background DB writer that executes callables from a queue."""

    def __init__(self, max_queue: int = 10000, name: str = "db_writer"):
        self._queue: "queue.Queue[Tuple[Callable, Tuple[Any, ...], dict]]" = queue.Queue(max_queue)
        self._thread: threading.Thread = None
        self._stop = threading.Event()
        self.name = name

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name=self.name, daemon=True)
        self._thread.start()

    def stop(self, wait: bool = True, timeout: float = 5.0) -> None:
        self._stop.set()
        if wait and self._thread:
            self._thread.join(timeout=timeout)

    def enqueue(self, func: Callable, *args, **kwargs) -> bool:
        try:
            self._queue.put_nowait((func, args, kwargs))
            return True
        except queue.Full:
            # If queue is full, drop or log
            return False

    def _run(self) -> None:
        while not self._stop.is_set() or not self._queue.empty():
            try:
                func, args, kwargs = self._queue.get(timeout=0.5)
            except queue.Empty:
                continue
            try:
                func(*args, **kwargs)
            except Exception:
                # swallow errors to keep writer running
                try:
                    import traceback

                    traceback.print_exc()
                except Exception:
                    pass
            finally:
                try:
                    self._queue.task_done()
                except Exception:
                    pass
            time.sleep(0)
