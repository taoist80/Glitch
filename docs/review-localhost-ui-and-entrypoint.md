# Code review: Localhost UI and entrypoint (agent + main)

Review of the code that enables the dashboard UI to work on localhost: entry point (`python -m glitch`), main startup, server binding, and CORS.

**Note:** No HTTP tunnel (e.g. ngrok, cloudflared) was found in the agent or main. Localhost support is achieved by binding the server to `0.0.0.0:8080` (so `http://localhost:8080` works) and allowing CORS from the Vite dev origin (`localhost:5173`). If you intended to add a tunnel for external access, that would be a separate change.

---

## 1. `agent/src/glitch/__main__.py`

**Purpose:** Convenience entry point so users can run `python -m glitch` from the repo and get a working agent + UI without manually setting PYTHONPATH or building the UI.

### What it does

- **`_ensure_pythonpath()`** – Inserts `agent/src` into `sys.path` so `glitch` and `main` resolve. Path is derived from `__file__` (e.g. `agent/src/glitch/__main__.py` → `agent/src`). Correct and robust.
- **`_auto_build_ui_if_needed()`** – If `ui/dist` does not exist but `ui/` does, runs `pnpm install` (if needed) and `pnpm build`. Uses `agent_dir.parent` as repo root, so `ui_dir = repo_root / "ui"` is correct for the standard layout.
- **`main()`** – Calls those two, then `from main import main as agent_main` and `asyncio.run(agent_main())`. Catches `KeyboardInterrupt` and generic `Exception`, prints and exits on fatal error.

### Issues and suggestions

| Item | Severity | Comment |
|------|----------|--------|
| **Import `from main import main`** | Low | When running as `python -m glitch`, the working directory and `sys.path` determine which `main` is loaded. If the process was started from `agent/`, `main` is `agent/main.py`. If started from repo root without `agent` on the path, `main` could be something else. `_ensure_pythonpath()` only adds `agent/src`, so it does not add `agent/` itself. So `main` resolves to `agent/main.py` only when the current working directory is such that `import main` finds `agent/main.py` (e.g. cwd is `agent/`). **Recommendation:** Document that `python -m glitch` should be run from the `agent/` directory (so that `import main` resolves to `agent/main.py`). Optionally add a quick check that `agent_main` is callable to fail fast if the wrong module was loaded. |
| **Duplicate UI build logic** | Low | UI can be built in two places: (1) `__main__.py` in `_auto_build_ui_if_needed()` before the server starts, and (2) `server.py` in `_setup_ui_routes()` via `_auto_build_ui()`. If the user runs `python -m glitch`, the UI is built in __main__ (if needed) and then the server starts; when `_setup_ui_routes()` runs, `ui_dist.is_dir()` is already true, so the server does not build again. If the user runs `python -m glitch.main` (or another path) and skips __main__, the server will still auto-build in _setup_ui_routes. So behavior is consistent; the only downside is maintaining two similar blocks (install + build). Consider extracting a single helper (e.g. in a small `glitch.ui_utils` or in server) and calling it from both __main__ and server. |
| **Stderr on build failure** | Low | `subprocess.run(..., capture_output=True)` hides output. On failure you decode stderr and print up to 300 chars. For a headless run that’s acceptable; for debugging, consider `capture_output=False` when `GLITCH_DEBUG` is set so the full pnpm output is visible. |
| **No `sys.exit(0)` on success** | Nit | After `asyncio.run(agent_main())` returns (e.g. Ctrl+C), the process exits with 0. Explicit `sys.exit(0)` is unnecessary. |

---

## 2. `agent/src/main.py`

**Purpose:** Initialize telemetry, create the agent, optionally start Telegram, then run the HTTP server (or interactive mode). Host/port and UI mode come from env.

### What it does

- **`get_server_config()`** – Reads `GLITCH_HOST` (default `0.0.0.0`), `GLITCH_PORT` (default `8080`), `GLITCH_DEBUG`. So by default the server binds to all interfaces on 8080, which makes **http://localhost:8080** work from the same machine.
- **`main()`** – Sets up telemetry, creates agent, optionally Telegram, then either `run_server_async(agent, server_config)` or interactive mode.

### Issues and suggestions

| Item | Severity | Comment |
|------|----------|--------|
| **Binding to 0.0.0.0** | Info | Default `GLITCH_HOST=0.0.0.0` is correct for containers and for local access (localhost:8080). For development, some teams prefer binding to `127.0.0.1` to avoid accepting connections from the network. You could document that setting `GLITCH_HOST=127.0.0.1` restricts to localhost only. No code change required. |
| **Port type** | Low | `int(os.getenv("GLITCH_PORT", "8080"))` can raise `ValueError` if the env var is not a valid integer. Catching and defaulting (or validating) would avoid a cryptic crash. |

---

## 3. `agent/src/glitch/server.py`

**Purpose:** Mount API and UI routes, optionally auto-build the UI, and run the app on the configured host/port.

### What it does

- **`_setup_ui_routes()`** – Resolves repo root and `ui/dist`, optionally calls `_auto_build_ui(ui_dir)` when not in dev mode and dist is missing, mounts static files at `/ui`.
- **`_auto_build_ui(ui_dir)`** – Runs `pnpm install` (if node_modules missing) and `pnpm build`; returns True on success. Logs and swallows errors (no re-raise).
- **`run_server()` / `run_server_async()`** – Call `_setup_api_routes()` and `_setup_ui_routes()`, then start the app with `config.host` and `config.port` (so localhost:8080 when using defaults).

### Issues and suggestions

| Item | Severity | Comment |
|------|----------|--------|
| **Path after failed auto-build** | Low | When `_auto_build_ui(ui_dir)` is called and fails, `ui_dist` is still the path that didn’t exist (e.g. `_repo_root / "ui" / "dist"`). The next check `if ui_mode != "dev" and ui_dist.is_dir()` is false, so you log "UI dist not found at ..." and don’t mount. Correct. One small inconsistency: in the `for base in ...` loop you set `ui_dist` and `ui_dir` per base; in the `else` branch you set `ui_dist = _repo_root / "ui" / "dist"` and `ui_dir = _repo_root / "ui"`. So after a failed build, the warning uses `ui_dist` which is correct. Fine as is. |
| **Blocking subprocess in async context** | Low | `_auto_build_ui()` uses synchronous `subprocess.run()`. It’s called from `_setup_ui_routes()`, which is called from `run_server_async()` before `await server.serve()`. So the event loop is running but blocked during the build. For a one-off build at startup that’s acceptable; if you ever want to avoid blocking the loop, run the build in `loop.run_in_executor()`. Optional. |

---

## 4. `agent/src/glitch/api/router.py` – CORS for localhost

**Purpose:** Allow the Vite dev server (and similar) to call the API from the browser.

### What it does

- **`add_cors_middleware(app)`** – Adds FastAPI CORS middleware with:
  - `allow_origins=["http://localhost:5173", "http://127.0.0.1:5173", "http://localhost:3000"]`
  - `allow_credentials=True`, `allow_methods=["*"]`, `allow_headers=["*"]`

So a page served from **http://localhost:5173** (Vite default) or **http://127.0.0.1:5173** or port 3000 can call **http://localhost:8080/api** and **http://localhost:8080/invocations** without being blocked by the browser.

### Issues and suggestions

| Item | Severity | Comment |
|------|----------|--------|
| **Origins are fixed** | Low | If someone runs Vite on a different port (e.g. 5174) or uses a different host, CORS will reject it. You could allow configuration via env (e.g. `GLITCH_CORS_ORIGINS`) and fall back to the current list. Optional. |
| **Production** | Info | In production the UI is usually served from the same origin as the API (e.g. same host:8080/ui), so CORS is not required for the static UI. CORS remains useful for dev (Vite on 5173 → API on 8080). No change needed. |

---

## 5. End-to-end localhost flow

1. User runs **`python -m glitch`** (typically from `agent/` or with PYTHONPATH including `agent/src`).
2. **__main__.py** sets PYTHONPATH and, if needed, builds the UI into `ui/dist`.
3. **main.py** `main()` runs and calls **run_server_async(agent, server_config)** with host `0.0.0.0` and port `8080`.
4. **server.py** mounts `/api` (with CORS) and `/ui` (static from `ui/dist`), then starts Uvicorn on `0.0.0.0:8080`.
5. User opens **http://localhost:8080/ui** for the built UI, or **http://localhost:5173** with Vite dev (which proxies `/api` and `/invocations` to localhost:8080). CORS allows the dev server to call the API.

No tunnel is involved; localhost works because the server binds to all interfaces and CORS allows the dev origin.

---

## Summary

| Area | Verdict |
|------|--------|
| **__main__.py** | Clear and correct; consider documenting that `import main` assumes run from agent (or equivalent) and optionally consolidating UI build with server. |
| **main.py** | Correct; optional improvement: validate or default `GLITCH_PORT` on invalid value. |
| **server.py** | Correct; optional: run UI build in executor to avoid blocking the event loop. |
| **CORS** | Correct for localhost:5173 and 3000; optional: make origins configurable. |
| **Tunnel** | No tunnel code present; localhost is enabled by binding and CORS. |

Overall the localhost UI path is consistent and works as intended. The suggestions above are minor hardening and maintainability improvements.
