#!/bin/sh
set -e
data="${DATA_DIR:-/app/data}"
mkdir -p "$data"
chown -R hop:hop "$data"
exec gosu hop python run.py
