"""Fixture: plain functions with calls and branches."""

import os  # noqa: F401
from pathlib import Path  # noqa: F401


def hello(name):
    """Say hello."""
    print(f"Hello, {name}")


def process_data(items):
    """Process items with branching."""
    if not items:
        return []

    results = []
    for item in items:
        transformed = transform(item)
        if transformed:
            results.append(transformed)
        else:
            log_error(item)
    return results


def transform(item):
    value = item.get("value")
    return cleanup(value)


def cleanup(value):
    return value.strip()


def log_error(item):
    print(f"Error: {item}")


class DataProcessor:
    """A simple class with methods."""

    def __init__(self, config):
        self.config = config

    def run(self):
        """Run the processor."""
        data = self.fetch_data()
        if data:
            return self.process(data)
        return None

    def fetch_data(self):
        return []

    def process(self, data):
        return [self.transform_item(d) for d in data]

    def transform_item(self, item):
        return item
