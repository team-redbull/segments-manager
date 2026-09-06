# Tests

Integration tests for the Segments Manager MongoDB backend. They run against a
**live server** (local process or container image) over HTTP.

## Layout

| File | Purpose |
|------|---------|
| `conftest.py` | Fixtures: server-reachability guard, auth, per-site CIDR helpers, auto-cleanup of created segments and allocated clusters |
| `test_api.py` | Full integration suite (health, validation, CRUD, per-site uniqueness, allocation, stats, auth) |

## Configuration

The suite is driven by environment variables (all optional):

| Variable | Default | Meaning |
|----------|---------|---------|
| `SEGMENTS_MANAGER_URL` | `http://127.0.0.1:8000` | Base URL of the running server |
| `SEGMENTS_MANAGER_API_TOKEN` | `test-token` | API token sent as `Authorization: Bearer` on write requests — **must match the server's `API_TOKEN`** |

The server under test must be configured with:

```
SITE_NETWORKS='{"site1": {"pool": "192.10.0.0/16", "dell-bmc": "10.50.0.0/16", "cisco-bmc": "10.60.0.0/16"}, "site2": {"pool": "193.51.0.0/16", "dell-bmc": "10.51.0.0/16", "cisco-bmc": "10.61.0.0/16"}, "site3": {"pool": "194.52.0.0/16", "dell-bmc": "10.52.0.0/16", "cisco-bmc": "10.62.0.0/16"}}'
API_TOKEN=test-token
```

If the server is unreachable, the whole suite **skips** (it does not fail).

## Running

### Against a local server

```bash
# terminal 1 — start the app (needs a MongoDB)
MONGODB_URL=mongodb://localhost:27017 \
SITE_NETWORKS='{"site1": {"pool": "192.10.0.0/16", "dell-bmc": "10.50.0.0/16", "cisco-bmc": "10.60.0.0/16"}, "site2": {"pool": "193.51.0.0/16", "dell-bmc": "10.51.0.0/16", "cisco-bmc": "10.61.0.0/16"}, "site3": {"pool": "194.52.0.0/16", "dell-bmc": "10.52.0.0/16", "cisco-bmc": "10.62.0.0/16"}}' \
API_TOKEN=test-token \
python main.py

# terminal 2
pip install pytest requests
pytest tests/ -v
```

### Against the container image

```bash
# start a MongoDB
podman run -d --name mongo -p 27017:27017 mongo:7

# start the app image, pointed at that MongoDB
podman run -d --name segments-manager --network host \
  -e MONGODB_URL="mongodb://127.0.0.1:27017" \
  -e SITE_NETWORKS='{"site1": {"pool": "192.10.0.0/16", "dell-bmc": "10.50.0.0/16", "cisco-bmc": "10.60.0.0/16"}, "site2": {"pool": "193.51.0.0/16", "dell-bmc": "10.51.0.0/16", "cisco-bmc": "10.61.0.0/16"}, "site3": {"pool": "194.52.0.0/16", "dell-bmc": "10.52.0.0/16", "cisco-bmc": "10.62.0.0/16"}}' \
  -e API_TOKEN="test-token" \
  docker.io/roi12345/segments-manager:mongodb

# run the tests against it
SEGMENTS_MANAGER_URL=http://127.0.0.1:8000 pytest tests/ -v
```

## Notes

- Tests are **self-cleaning**: every segment created and every cluster
  allocated is removed on teardown, so they are safe to run repeatedly and
  against a shared database.
- VLAN IDs are drawn from a randomized high band per session to avoid
  colliding with real data.
