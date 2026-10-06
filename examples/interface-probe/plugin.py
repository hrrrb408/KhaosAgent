from khaos.ipc import IPCProtocolError
from khaos.runner_sdk import fs_write


def run(request):
    if (
        type(request) is not dict
        or set(request) != {"operation", "topic", "message"}
        or request["operation"] != "publish"
    ):
        raise ValueError("publish requires operation, topic, and message")

    topic = request["topic"]
    message = request["message"]
    if (
        type(topic) is not str
        or not topic
        or len(topic.encode("utf-8")) > 128
        or type(message) is not str
        or not message
        or len(message.encode("utf-8")) > 2_048
    ):
        raise ValueError("topic and message must be bounded non-empty strings")

    try:
        fs_write("interface-probe-scope-escape.txt", b"must be denied")
    except IPCProtocolError as error:
        if "path_not_writable" not in str(error):
            raise
        unscoped_write_denied = True
    else:
        unscoped_write_denied = False

    return {
        "published": True,
        "topic": topic,
        "message": message,
        "unscoped_write_denied": unscoped_write_denied,
    }
