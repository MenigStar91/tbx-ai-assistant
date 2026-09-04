from collections import OrderedDict


class ExportStore:
    def __init__(self, capacity: int = 50):
        self.capacity = capacity
        self._values: OrderedDict[str, str] = OrderedDict()

    def put(self, export_id: str, content: str) -> None:
        self._values[export_id] = content
        self._values.move_to_end(export_id)
        while len(self._values) > self.capacity:
            self._values.popitem(last=False)

    def get(self, export_id: str) -> str | None:
        return self._values.get(export_id)


export_store = ExportStore()

