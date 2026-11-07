"""Stand-in model: a tiny local server that answers in Anthropic's Messages
format with scripted replies and records the requests it received."""

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer


def text_reply(text: str) -> dict:
    return {
        "id": "msg_standin", "type": "message", "role": "assistant", "model": "standin",
        "content": [{"type": "text", "text": text}],
        "stop_reason": "end_turn", "usage": {"input_tokens": 1, "output_tokens": 1},
    }


def tool_use_reply(name: str, tool_input: dict, tool_id: str = "toolu_standin") -> dict:
    return {
        "id": "msg_standin", "type": "message", "role": "assistant", "model": "standin",
        "content": [{"type": "tool_use", "id": tool_id, "name": name, "input": tool_input}],
        "stop_reason": "tool_use", "usage": {"input_tokens": 1, "output_tokens": 1},
    }


def error_reply(status: int, message: str) -> tuple[int, dict]:
    return status, {"error": {"code": status, "message": message}}


class StandInModel:
    """Replies are consumed in order. Each is a reply dict (status 200) or a
    `(status, body)` tuple. After the script runs out, requests get a 500."""

    def __init__(self, replies=()):
        self.replies = list(replies)
        self.requests = []  # each: {"path", "headers", "body"}
        standin = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                length = int(self.headers.get("content-length", 0))
                body = json.loads(self.rfile.read(length) or b"null")
                standin.requests.append(
                    {"path": self.path, "headers": {k.lower(): v for k, v in self.headers.items()}, "body": body})
                if standin.replies:
                    reply = standin.replies.pop(0)
                    status, payload = reply if isinstance(reply, tuple) else (200, reply)
                else:
                    status, payload = error_reply(500, "stand-in model has no scripted reply left")
                data = json.dumps(payload).encode()
                self.send_response(status)
                self.send_header("content-type", "application/json")
                self.send_header("content-length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def log_message(self, *args):
                pass

        self._server = HTTPServer(("127.0.0.1", 0), Handler)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)

    @property
    def endpoint(self) -> str:
        return f"http://127.0.0.1:{self._server.server_port}/v1/messages"

    def __enter__(self):
        self._thread.start()
        return self

    def __exit__(self, *exc):
        self._server.shutdown()
        self._server.server_close()
