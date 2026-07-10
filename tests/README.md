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
| `VLAN_AUTH_USER` | `admin` | Basic-auth username |
| `VLAN_AUTH_PASS` | `admin` | Basic-auth password |

The server under test must be configured with:

```
SITES=site1,site2,site3
SITE_PREFIXES=site1:192,site2:193,site3:194
```

If the server is unreachable, the whole suite **skips** (it does not fail).

## Running

### Against a local server

```bash
# terminal 1 — start the app (needs a MongoDB)
MONGODB_URL=mongodb://localhost:27017 \
SITES=site1,site2,site3 SITE_PREFIXES=site1:192,site2:193,site3:194 \
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
  -e SITES="site1,site2,site3" \
  -e SITE_PREFIXES="site1:192,site2:193,site3:194" \
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
