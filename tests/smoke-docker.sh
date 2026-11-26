#!/bin/sh
set -eu

root=$(CDPATH='' cd -- "$(dirname -- "$0")/.." && pwd)
work=$(mktemp -d)
project="ipad-panel-smoke-$$"
image="$project-ipad-panel"
compose() { docker compose -p "$project" "$@"; }
cleanup() {
    docker rm -f "$project-haos" "$project-supervisor" >/dev/null 2>&1 || true
    compose down --remove-orphans >/dev/null 2>&1 || true
    rm -rf "$work"
}
trap cleanup EXIT
cd "$work"
cp "$root/compose.yaml" .
cp "$root/panel.example.json" panel.json
cp -R "$root/ipad_panel" .
export PANEL_BIND_IP=127.0.0.1 PANEL_PORT=0 HA_URL= HA_TOKEN=
compose config -q
compose up -d --build

check_page() {
    container=$1 expected=$2
    for _ in $(seq 1 20); do
        if docker exec "$container" python -c '
import sys
from urllib.request import urlopen
with urlopen("http://127.0.0.1:8090/", timeout=2) as response:
    body = response.read().decode()
assert sys.argv[1] in body
assert "smoke-token" not in body
' "$expected" >/dev/null 2>&1; then
            printf 'Verified %s: %s\n' "$container" "$expected"
            return
        fi
        sleep 1
    done
    docker logs "$container"
    return 1
}

check_page "$(compose ps -q ipad-panel)" "Demo"
docker run -d --name "$project-supervisor" --network "${project}_default" --network-alias supervisor \
    --entrypoint python "$image" -u -c '
from http.server import BaseHTTPRequestHandler, HTTPServer
class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        endpoints = {"/api/states/sensor.room": "21.5", "/core/api/states/sensor.room": "23.7"}
        if self.path not in endpoints or self.headers.get("Authorization") != "Bearer smoke-token":
            self.send_error(401)
            return
        self.send_response(200)
        self.end_headers()
        self.wfile.write(("{\"state\":\"" + endpoints[self.path] + "\"}").encode())
HTTPServer(("0.0.0.0", 80), Handler).serve_forever()
' >/dev/null
printf '%s\n' '{"demo":false,"timezone":"Europe/Berlin","entities":[{"id":"sensor.room"}]}' > panel.json
HA_URL=http://supervisor HA_TOKEN=smoke-token compose up -d --force-recreate
check_page "$(compose ps -q ipad-panel)" "21.5"

docker run -d --name "$project-haos" --network "${project}_default" \
    -e SUPERVISOR_TOKEN=smoke-token --entrypoint sh "$image" -c '
        mkdir -p /data
        umask 077
        printf "%s\n" "{\"demo\":false,\"entities\":[{\"id\":\"sensor.room\"}]}" > /data/options.json
        exec python /app/panel.py
    ' >/dev/null
check_page "$project-haos" "23.7"
docker exec "$project-haos" grep -Eq '^Uid:[[:space:]]+10001[[:space:]]' /proc/1/status
printf '%s\n' 'Verified HAOS startup reads root-only options and drops privileges'
