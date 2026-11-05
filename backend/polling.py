"""Spread fleet startup and avoid synchronized retries after collection failures."""
import random
import math


class FleetSchedule:
    """Even fleet-wide slots also spread every subset sharing a jump host.

    Deadlines use a monotonic clock. A membership/interval change spreads the
    next round across the new period; missed rounds are never replayed.
    """
    def __init__(self):
        self.signature = None
        self.due, self.phase, self.failures = {}, {}, {}

    def reconcile(self, ids, interval, now):
        ids = tuple(ids)
        signature = (ids, interval)
        if signature == self.signature:
            return
        self.signature, self.interval = signature, interval
        ids = tuple(sorted(ids))
        self.phase = {key: now + index * interval / len(ids) for index, key in enumerate(ids)}
        self.due = {key: max(at, self.due.get(key, at)) if self.failures.get(key) else at
                    for key, at in self.phase.items()}
        self.failures = {key: self.failures.get(key, 0) for key in ids}

    def finish(self, key, now, failed):
        if key not in self.phase:
            return
        self.failures[key] = min(8, self.failures[key] + 1) if failed else 0
        if failed:
            self.due[key] = now + collection_delay(self.interval, self.failures[key])
        else:
            phase = self.phase[key]
            self.due[key] = phase + max(0, math.floor((now-phase)/self.interval)+1)*self.interval


def startup_delay():
    return random.uniform(0, 3)


def collection_delay(interval, failures):
    if failures <= 0:
        return interval
    base = min(interval * 2 ** min(failures - 1, 7), 120)
    return random.uniform(base * .8, min(base * 1.2, 120))
