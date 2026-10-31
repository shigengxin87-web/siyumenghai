#!/usr/bin/env python3
import sys

path = "/etc/nginx/sites-enabled/siyumenghai-main"
src = open(path, encoding="utf-8").read()

if "/ai-admin/" in src:
    print("already patched")
    sys.exit(0)

block = '''
    location = /ai-admin {
        return 301 /ai-admin/;
    }

    location ^~ /ai-admin/ {
        proxy_pass http://127.0.0.1:8090/;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        client_max_body_size 30m;
        proxy_read_timeout 120s;
        proxy_buffering off;
    }

'''

anchor = "    location / {"
idx = src.find(anchor)
if idx == -1:
    print("anchor not found")
    sys.exit(1)

src = src[:idx] + block + src[idx:]
open(path, "w", encoding="utf-8").write(src)
print("patched")
