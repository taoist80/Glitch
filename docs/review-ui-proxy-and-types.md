# Code review: UI proxy and related changes

Review of the UI proxy, static UI mounting, and proxy routes. Focus: correctness, types, and use of existing libraries.

---

## P0 – Correctness / contract issues

### 1. `server.py`: `invoke()` return type vs `_ui_api_request` response

**File:** `agent/src/glitch/server.py`  
**Symbol:** `invoke`, `_handle_ui_api_request`

**Issue:** The entrypoint is annotated as `-> InvocationResponse`, but when the payload contains `_ui_api_request`, the handler returns `await _handle_ui_api_request(...)`, which returns a **dict** (e.g. status, telegram config, API errors), not an `InvocationResponse`. That violates the declared contract and can confuse type checkers and maintainers.

**Fix:** Reflect the real return type and document the two shapes:

```python
from typing import Any, Union

# At top with other type aliases:
# When _ui_api_request is used, the runtime gets an API response dict, not InvocationResponse.
InvocationEntrypointResult = Union[InvocationResponse, dict[str, Any]]

@app.entrypoint
async def invoke(payload: InvocationRequest, context: RequestContext) -> InvocationEntrypointResult:
    ...
    if "_ui_api_request" in payload:
        return await _handle_ui_api_request(payload["_ui_api_request"])  # dict
    ...
```

---

### 2. `server.py`: Static UI path points at wrong directory

**File:** `agent/src/glitch/server.py`  
**Symbol:** `_setup_ui_routes`, `workspace`, `ui_dist`

**Issue:** The comment says “Repo root: agent/src/glitch -> agent -> workspace”, and `workspace = Path(__file__).resolve().parent.parent.parent` is the **agent** directory. So `ui_dist = workspace / "ui" / "dist"` is **agent/ui/dist**. In this repo, `ui/` lives next to `agent/` (repo root), not inside it, so the static UI is never found when running from the repo.

**Fix:** Resolve the repo root (one level above `agent`) and prefer it when `ui/dist` exists there:

```python
def _setup_ui_routes() -> None:
    from starlette.staticfiles import StaticFiles

    ui_mode = os.getenv("GLITCH_UI_MODE", "local")
    # agent/src/glitch/server.py -> glitch -> src -> agent -> (repo root)
    _agent_dir = Path(__file__).resolve().parent.parent.parent
    _repo_root = _agent_dir.parent
    # Prefer repo layout (ui/ beside agent/); fallback to agent/ui (e.g. container with baked-in dist)
    for base in (_repo_root, _agent_dir):
        ui_dist = base / "ui" / "dist"
        if ui_dist.is_dir():
            break
    else:
        ui_dist = _agent_dir / "ui" / "dist"  # may not exist

    if ui_mode != "dev" and ui_dist.is_dir():
        app.mount("/ui", StaticFiles(directory=str(ui_dist), html=True), name="ui")
        logger.info("UI dashboard mounted at /ui")
    ...
```

---

## P1 – Reliability / maintainability

### 3. `ui_proxy_routes.py`: Unbounded `_proxy_sessions` growth

**File:** `agent/src/glitch/ui_proxy_routes.py`  
**Symbol:** `_proxy_sessions`

**Issue:** `_proxy_sessions: dict[str, str] = {}` grows with every distinct `X-Client-Id`. There is no eviction, so long-lived processes can leak memory.

**Fix:** Use a bounded or TTL cache. With the standard library you can cap size and evict oldest:

```python
from collections import OrderedDict

class _BoundedSessionDict(OrderedDict):
    """Max 1000 client IDs; evict oldest when full."""
    MAX = 1000

    def __setitem__(self, key, value):
        super().__setitem__(key, value)
        if len(self) > self.MAX:
            self.popitem(last=False)

_proxy_sessions: _BoundedSessionDict = _BoundedSessionDict()
```

Alternatively, use `cachetools.TTLCache(maxsize=1000, ttl=3600)` if you add `cachetools` to dependencies.

---

### 4. `ui_proxy.py`: Deprecated `asyncio.get_event_loop()`

**File:** `agent/src/glitch/ui_proxy.py`  
**Symbol:** `invoke_deployed_agent_async`

**Issue:** `loop = asyncio.get_event_loop()` is deprecated in Python 3.10+ when used from async code. In an async function you should use the running loop.

**Fix:** Use `get_running_loop()` and pass it to `run_in_executor`:

```python
async def invoke_deployed_agent_async(
    agent_name: str,
    region: str,
    payload: dict,
    session_id: Optional[str] = None,
    runtime_arn: Optional[str] = None,
) -> dict:
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(
        None,
        lambda: invoke_deployed_agent(
            agent_name=agent_name,
            region=region,
            payload=payload,
            session_id=session_id,
            runtime_arn=runtime_arn,
        ),
    )
```

---

### 5. `ui_proxy.py`: Response stream not closed

**File:** `agent/src/glitch/ui_proxy.py`  
**Symbol:** `invoke_deployed_agent`, `body`

**Issue:** `body = response.get("response")` is typically a streaming body (e.g. `StreamingBody`). After `raw = body.read()`, the stream is not closed. That can leave resources open and cause warnings in some environments.

**Fix:** Ensure the body is read and closed (e.g. with a try/finally or context manager if the type supports it). For a simple read-once body:

```python
body = response.get("response")
if body is None:
    return {"error": "Empty response from agent"}

try:
    raw = body.read()
finally:
    if hasattr(body, "close"):
        body.close()
if not raw:
    return {"error": "Empty response body"}
```

---

### 6. `ui_proxy_routes.py`: Handler type for `ProxyApp`

**File:** `agent/src/glitch/ui_proxy_routes.py`  
**Symbol:** `ProxyApp`, `invocations_handler`

**Issue:** `invocations_handler` is untyped, so it’s unclear what the mount point expects and static checking is weaker.

**Fix:** Use a type alias and annotate the constructor:

```python
from typing import Awaitable, Callable

from starlette.requests import Request
from starlette.responses import JSONResponse

AsyncRouteHandler = Callable[[Request], Awaitable[JSONResponse]]

class ProxyApp:
    __slots__ = ("api_router", "invocations_handler")

    def __init__(
        self,
        api_router: Starlette,
        invocations_handler: AsyncRouteHandler,
    ) -> None:
        self.api_router = api_router
        self.invocations_handler = invocations_handler
```

---

### 7. `server.py`: Skill toggle path parsing is brittle

**File:** `agent/src/glitch/server.py`  
**Symbol:** `_handle_ui_api_request`, skill toggle branch

**Issue:** `skill_id = path.split("/")[2]` assumes a path like `/skills/{id}/toggle`. For `/skills//toggle` you get an empty string; for `/skills/foo/bar/toggle` you get `foo` and ignore `bar`. The FastAPI router uses a path parameter, so behavior should match the real API.

**Fix:** Use a regex or explicit checks so the segment between `/skills/` and `/toggle` is the skill id and non-empty:

```python
elif path.startswith("/skills/") and path.endswith("/toggle") and method == "POST":
    # Path: /skills/{skill_id}/toggle
    parts = path.strip("/").split("/")
    if len(parts) >= 3 and parts[0] == "skills" and parts[-1] == "toggle":
        skill_id = parts[1]
        if skill_id:
            ...
        else:
            return {"error": "Missing skill_id in path"}
    else:
        return {"error": f"Invalid path: {path}"}
```

(Alternatively, use a single regex like `r"^/skills/([^/]+)/toggle$"` and reject if it doesn’t match.)

---

## P2 – Types and libraries

### 8. TypedDict for `_ui_api_request` payload

**File:** `agent/src/glitch/types.py` (or `server.py`)  
**Symbol:** payload shape for `_ui_api_request`

**Issue:** The shape of `_ui_api_request` (path, method, body) is only documented in comments and in `create_api_proxy_payload`. There’s no single typed definition used by the server and the proxy.

**Suggestion:** Add a TypedDict in `glitch/types.py` and use it in the server and in `ui_proxy.create_api_proxy_payload`:

```python
# In glitch/types.py (or glitch/api/types.py)
class UiApiRequest(TypedDict, total=False):
    path: str
    method: str
    body: Optional[Dict[str, Any]]

# In server.py
def _handle_ui_api_request(api_request: UiApiRequest) -> dict:
    path = api_request.get("path", "")
    ...

# In ui_proxy.py
def create_api_proxy_payload(path: str, method: str, body: Any = None) -> dict:
    return {"_ui_api_request": {"path": path, "method": method.upper(), "body": body}}
```

You can then type `create_api_proxy_payload` to return `dict` with a `_ui_api_request` key of type `UiApiRequest`, or a small wrapper TypedDict.

---

### 9. `InvocationRequest` and `_ui_api_request`

**File:** `agent/src/glitch/types.py`  
**Symbol:** `InvocationRequest`

**Issue:** The runtime accepts payloads that are either `{ "prompt": "...", ... }` or `{ "_ui_api_request": { ... } }`. The current `InvocationRequest` doesn’t include `_ui_api_request`, so it doesn’t match the real contract.

**Suggestion:** Extend the TypedDict so the payload type is accurate:

```python
class _InvocationRequestRequired(TypedDict):
    pass  # or prompt if you make it required when not _ui_api_request

class InvocationRequest(_InvocationRequestRequired, total=False):
    prompt: str
    session_id: Optional[str]
    context: Optional[Dict[str, Any]]
    stream: bool
    _ui_api_request: Dict[str, Any]  # UiApiRequest when present
```

Then the entrypoint’s payload type matches what the runtime actually sends.

---

### 10. Logging style

**File:** `agent/src/glitch/server.py`, `agent/src/glitch/ui_proxy_routes.py`  
**Symbol:** Various `logger.info` / `logger.error` calls

**Issue:** Some calls use f-strings (e.g. `logger.info(f"UI API request: {method} {path}")`) while the rest of the codebase and the plan prefer `%s`-style for logging (so parameters are only formatted if the log level is enabled).

**Fix:** Use `logger.info("UI API request: %s %s", method, path)` and similar where you currently use f-strings in log calls.

---

## Summary

| Priority | Item | File(s) |
|----------|------|--------|
| P0 | Invoke return type (Union with dict) | server.py |
| P0 | Static UI path (repo root vs agent) | server.py |
| P1 | Bounded or TTL proxy sessions | ui_proxy_routes.py |
| P1 | get_running_loop() in async proxy | ui_proxy.py |
| P1 | Close response body after read | ui_proxy.py |
| P1 | Type ProxyApp.invocations_handler | ui_proxy_routes.py |
| P1 | Robust skill path parsing | server.py |
| P2 | TypedDict for _ui_api_request | types.py, server.py, ui_proxy.py |
| P2 | InvocationRequest includes _ui_api_request, stream | types.py |
| P2 | Logging %s instead of f-strings | server.py, ui_proxy_routes.py |

---

## Decision: **Request changes**

The two P0 items (entrypoint return type and static UI path) should be fixed so behavior and types match reality and the UI is found when running from the repo. The P1 items (sessions growth, event loop, body close, handler type, path parsing) improve robustness and maintainability with small, localized changes. P2 improvements (TypedDicts and logging) align the code with existing patterns and make the dataflow easier to reason about.
