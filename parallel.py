"""Run per-shot jobs with a cap on how many are in flight at once."""

from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor

from common import StepError


class TaskRunner:
    """workers <= 1 runs each task inline at submit time, exactly like a plain loop (the fal
    path). workers > 1 runs up to that many at once; join() waits for all of them, so finished
    shots are saved even when another fails, then raises the first error."""

    def __init__(self, workers: int):
        self.workers = max(1, int(workers))
        self._pool = ThreadPoolExecutor(max_workers=self.workers) if self.workers > 1 else None
        self._futures: list[Future] = []

    def submit(self, fn, *args) -> None:
        if self._pool is None:
            fn(*args)
        else:
            self._futures.append(self._pool.submit(fn, *args))

    def join(self) -> None:
        if self._pool is None:
            return
        errors = []
        for fut in self._futures:
            exc = fut.exception()
            if exc is not None:
                errors.append(exc)
        self._pool.shutdown(wait=True)
        if errors:
            for extra in errors[1:]:
                print(f"  also failed: {extra}")
            if isinstance(errors[0], StepError):
                raise errors[0]
            raise StepError(f"{type(errors[0]).__name__}: {errors[0]}") from errors[0]
