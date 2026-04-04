"""Fixture: data store — simple key-value operations."""


class Store:
    def __init__(self):
        self._data = {}

    def get(self, key):
        return self._data.get(key)

    def put(self, key, value):
        self._data[key] = value

    def delete(self, key):
        self._data.pop(key, None)

    def list_keys(self):
        return list(self._data.keys())
