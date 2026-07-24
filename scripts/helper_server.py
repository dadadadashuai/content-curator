#!/usr/bin/env python3
"""Tiny helper server that runs yt-dlp on the host for the bili-helper container."""
import subprocess, json, sys
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

COOKIES = "/home/ds/ai-suite/bili-helper/cookies.txt"

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)
        
        if parsed.path == "/bvids":
            uid = params.get("uid", [""])[0]
            if not uid:
                self._json({"error": "need uid"})
                return
            try:
                cmd = ["yt-dlp", "--flat-playlist", "--print", "%(id)s",
                       "--cookies", COOKIES, "--no-warnings",
                       "--no-check-certificates", "--playlist-end", "200",
                       f"https://space.bilibili.com/{uid}/video"]
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=90)
                bvids = [l.strip() for l in result.stdout.strip().split("\n") 
                         if l.strip().startswith("BV")]
                self._json({"bvids": bvids})
            except Exception as e:
                self._json({"error": str(e)})
        else:
            self._json({"error": "unknown endpoint"})
    
    def _json(self, data):
        body = json.dumps(data).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", len(body))
        self.end_headers()
        self.wfile.write(body)
    
    def log_message(self, *args):
        pass  # quiet

print("Helper server on :9101")
HTTPServer(("127.0.0.1", 9101), Handler).serve_forever()
