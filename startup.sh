#!/bin/sh
cd /workspace
if ! curl -sf -o /dev/null --max-time 1 http://127.0.0.1:8080/; then
  npm run dev
fi
