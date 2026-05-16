#!/bin/bash
set -e
echo "PORT env value: '${PORT:-not set}'"
uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8080}
