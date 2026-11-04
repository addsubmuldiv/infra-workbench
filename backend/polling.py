"""Spread fleet startup and avoid synchronized retries after collection failures."""
import random


def startup_delay():
    return random.uniform(0, 3)


def collection_delay(interval, failures):
    if failures <= 0:
        return interval
    base = min(interval * 2 ** min(failures - 1, 7), 120)
    return random.uniform(base * .8, min(base * 1.2, 120))
