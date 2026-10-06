import json
import unicodedata

from khaos.runner_sdk import state_read, state_replace


_FORMAT = "khaos-memory-v1"


def _canonical(value):
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8", errors="strict")


def _key(value):
    if type(value) is not str or not value or len(value.encode("utf-8")) > 128:
        raise ValueError("key must be a non-empty string of at most 128 UTF-8 bytes")
    return value


def _load_items():
    data = state_read()
    if data is None or data == b"":
        return {}
    value = json.loads(data.decode("utf-8", errors="strict"))
    if (
        type(value) is not dict
        or set(value) != {"format", "items"}
        or value["format"] != _FORMAT
        or type(value["items"]) is not dict
        or any(type(key) is not str or type(item) is not str
               for key, item in value["items"].items())
        or _canonical(value) != data
    ):
        raise ValueError("Memory state is not canonical khaos-memory-v1 data")
    return value["items"]


def _normalized_key(value):
    return unicodedata.normalize("NFKC", value).casefold()


def run(request):
    if type(request) is not dict or type(request.get("operation")) is not str:
        raise ValueError("operation is required")
    operation = request["operation"]
    key = _key(request.get("key"))
    items = _load_items()

    if operation == "remember":
        value = request.get("value")
        if type(value) is not str or len(value.encode("utf-8")) > 4_096:
            raise ValueError("value must be a string of at most 4096 UTF-8 bytes")
        items[key] = value
        state_replace(_canonical({"format": _FORMAT, "items": items}))
        return {"operation": operation, "key": key, "remembered": True}

    if operation == "recall":
        value = items.get(key)
        if value is None:
            query = _normalized_key(key)
            matches = [
                stored_key
                for stored_key in items
                if _normalized_key(stored_key) == query
            ]
            if len(matches) == 1:
                value = items[matches[0]]
        return {
            "operation": operation,
            "key": key,
            "found": value is not None,
            "value": value,
        }

    if operation == "forget":
        existed = key in items
        if existed:
            del items[key]
            state_replace(_canonical({"format": _FORMAT, "items": items}))
        return {"operation": operation, "key": key, "forgotten": existed}

    raise ValueError("operation must be remember, recall, or forget")
