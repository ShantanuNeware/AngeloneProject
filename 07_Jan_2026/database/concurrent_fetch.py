# database/concurrent_fetch.py
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Callable, List, Dict, Any


def parallel_map(
    func: Callable[[Any], Any],
    items: List[Any],
    max_workers: int = 10,
    timeout: float = 5.0,
) -> Dict[Any, Any]:
    """
    Run `func(item)` for each item in parallel, returning dict of item -> result.
    """
    results = {}
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_map = {executor.submit(func, item): item for item in items}
        for future in as_completed(future_map, timeout=None):
            item = future_map[future]
            try:
                results[item] = future.result(timeout=timeout)
            except Exception:
                results[item] = None
    return results
