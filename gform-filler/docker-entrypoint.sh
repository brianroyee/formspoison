#!/usr/bin/env bash
set -e

if [ -z "$DISPLAY" ]; then
  export DISPLAY=:99
fi

mkdir -p /tmp/.X11-unix

if [ "${FORM_FILLER_HEADLESS:-1}" = "1" ] || [ "${FORM_FILLER_HEADLESS:-0}" = "true" ] || [ "${FORM_FILLER_HEADLESS:-0}" = "yes" ]; then
  Xvfb :99 -screen 0 1280x1024x24 >/tmp/xvfb.log 2>&1 &
fi

exec "$@"
