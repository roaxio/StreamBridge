#!/bin/sh
# Start StreamBridge from the folder this script is in.
cd "$(dirname "$0")" && exec ./StreamBridge "$@"
