import json
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer

FIXTURE = json.loads(open(sys.argv[1]).read())


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        body = FIXTURE.get(self.path.split("?")[0])
        if body is None:
            self.send_response(500)
            self.end_headers()
            return
        payload = json.dumps(body).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, fmt, *args):
        pass


if __name__ == "__main__":
    HTTPServer(("0.0.0.0", int(sys.argv[2])), Handler).serve_forever()
