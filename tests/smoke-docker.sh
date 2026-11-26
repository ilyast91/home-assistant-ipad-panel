#!/bin/sh
set -eu

root=$(CDPATH='' cd -- "$(dirname -- "$0")/.." && pwd)
work=$(mktemp -d)
project="ipad-panel-smoke-$$"
image="${1:-$project-ipad-panel}"
compose() { docker compose -p "$project" "$@"; }
cleanup() {
    docker rm -f "$project-haos" "$project-supervisor" >/dev/null 2>&1 || true
    compose down --volumes --remove-orphans >/dev/null 2>&1 || true
    if [ "$image" = "$project-ipad-panel" ]; then
        docker image rm "$image" >/dev/null 2>&1 || true
    fi
    rm -rf "$work"
}
trap cleanup EXIT
cd "$work"
cp "$root/compose.yaml" .
cp "$root/panel.example.json" panel.json
cp -R "$root/ipad_panel" .
export PANEL_BIND_IP=127.0.0.1 PANEL_PORT=0 HA_URL= HA_TOKEN= PANEL_PASSWORD=
compose config -q
if [ "$#" -eq 0 ]; then
    compose up -d --build
else
    docker image inspect "$image" >/dev/null
    printf 'services:\n  ipad-panel:\n    image: "%s"\n    pull_policy: never\n' "$image" > compose.override.yaml
    compose up -d --no-build
fi

check_panel() {
    container=$1 mode=$2
    docker exec -i "$container" python - "$mode" "$PANEL_PASSWORD" < "$root/tests/container_check.py" || {
        docker logs "$container" 2>&1 | grep -v 'Generated panel password:'
        return 1
    }
}
container=$(compose ps -q ipad-panel)
for _ in $(seq 1 12); do
    generated=$(docker logs "$container" 2>&1 | awk '/^Generated panel password:/ {print $NF}')
    health=$(docker inspect --format '{{.State.Health.Status}}' "$container")
    if [ -n "$generated" ] && [ "$health" = healthy ]; then break; fi
    sleep 1
done
test "${#generated}" -eq 24
test "$health" = healthy
PANEL_PASSWORD=$generated check_panel "$container" generated
compose up -d --force-recreate
container=$(compose ps -q ipad-panel)
PANEL_PASSWORD=$generated check_panel "$container" generated
if docker logs "$container" 2>&1 | grep -q 'Generated panel password:'; then exit 1; fi
export PANEL_PASSWORD=ab1234
compose up -d --force-recreate
check_panel "$(compose ps -q ipad-panel)" demo

docker run -d --name "$project-supervisor" --network "${project}_default" --network-alias supervisor \
    --entrypoint python "$image" -u -c '
import json
from http.server import BaseHTTPRequestHandler, HTTPServer
entity = {"entity_id": "light.fake_kitchen", "state": "off", "attributes": {"friendly_name": "Fake kitchen light"}}
class Handler(BaseHTTPRequestHandler):
    def reply(self, value):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(json.dumps(value).encode())
    def endpoint(self):
        if self.headers.get("Authorization") != "Bearer smoke-token":
            self.send_error(401)
            return None
        return self.path.removeprefix("/core")
    def do_GET(self):
        endpoint = self.endpoint()
        if endpoint == "/api/states":
            self.reply([entity])
        elif endpoint == "/api/states/light.fake_kitchen":
            self.reply(entity)
        elif endpoint:
            self.send_error(404)
    def do_POST(self):
        endpoint = self.endpoint()
        if not endpoint:
            return
        data = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        if endpoint not in {"/api/services/light/turn_on", "/api/services/light/turn_off"} or data != {"entity_id": "light.fake_kitchen"}:
            self.send_error(400)
            return
        entity["state"] = endpoint.rsplit("_", 1)[1]
        self.reply([entity])
HTTPServer(("0.0.0.0", 80), Handler).serve_forever()
' >/dev/null

printf '%s\n' '{"demo":false,"timezone":"Europe/Berlin"}' > panel.json
export HA_URL=http://supervisor HA_TOKEN=smoke-token
compose up -d --force-recreate
check_panel "$(compose ps -q ipad-panel)" compose
compose up -d --force-recreate
check_panel "$(compose ps -q ipad-panel)" persisted

docker run -d --name "$project-haos" --network "${project}_default" \
    -e SUPERVISOR_TOKEN=smoke-token --entrypoint sh "$image" -c '
        mkdir -p /data
        umask 077
        printf "%s\n" "{\"demo\":false,\"panel_password\":\"ab1234\"}" > /data/options.json
        exec python /app/panel.py
    ' >/dev/null
check_panel "$project-haos" haos
