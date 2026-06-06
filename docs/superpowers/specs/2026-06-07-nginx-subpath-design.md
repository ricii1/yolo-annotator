# Nginx Subpath Deployment Support

**Date:** 2026-06-07
**Status:** Approved

## Summary

Make the YOLO Annotator deployable at a URL subpath (e.g. `/annotator/`) behind an nginx reverse proxy, without code changes at deploy time beyond setting one environment variable.

## Problem

All API calls in `api.js` use absolute paths (`/api/images`, `/api/classes`, etc.) and all static asset references in `index.html` use absolute paths (`/js/api.js`, `/css/app.css`). When nginx strips a subpath prefix and forwards to the app, the app itself is happy, but the browser resolves `fetch('/api/images')` against the origin root — not the subpath — so API calls bypass the nginx proxy entirely and 404.

## Solution

Add a `<base href="/">` element to `index.html`. At deploy time, set `ROOT_PATH=/annotator/` (env var). The app injects the correct `<base href="/annotator/">` into the served HTML. All relative URLs in both HTML and JS resolve against the base href automatically.

## Environment Variable

| Variable | Default | Example |
|----------|---------|---------|
| `ROOT_PATH` | `/` | `/annotator/` |

Must end with `/`. If omitted, app behaves exactly as today (no change for existing deployments).

## Architecture

### `app/config.py`

Add:
```python
root_path: str = Field(default="/", env="ROOT_PATH")
```

Validation: ensure value starts with `/`; auto-append trailing `/` if missing. Strip doubled slashes.

### `app/main.py`

Replace the `StaticFiles` catch-all mount with an explicit `GET /` route that:
1. Reads `static/index.html` as text once at startup (cache it in app state)
2. Replaces the literal string `<base href="/">` with `<base href="{settings.root_path}">`
3. Returns the modified HTML with `Content-Type: text/html`

Keep `StaticFiles` mounted for everything else (`/js/`, `/css/`, `/images/`). The `StaticFiles(html=True)` already handled `GET /` → `index.html`; now an explicit route takes over only that one path, and StaticFiles continues serving all other static assets.

### `static/index.html`

Two changes:
1. Add `<base href="/">` as the first element inside `<head>`.
2. Remove the leading `/` from all static asset references:
   - `<link href="/css/app.css">` → `<link href="css/app.css">`
   - `<script src="/js/api.js">` → `<script src="js/api.js">` (and all other scripts)

### `static/js/api.js`

Remove the leading `/` from all fetch URLs:
- `/api/images` → `api/images`
- `/api/search/by-upload` → `api/search/by-upload`
- etc. (all occurrences of `"/api/`)

The browser resolves these relative URLs against `document.baseURI` (set by `<base href>`), producing the correct full path including the subpath prefix.

## Nginx Config (for operators)

```nginx
location /annotator/ {
    proxy_pass http://localhost:1234/;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
}
```

Start uvicorn with:
```bash
ROOT_PATH=/annotator/ python -m uvicorn app.main:app --host 0.0.0.0 --port 1234
```

## Behaviour at Root (no change)

With default `ROOT_PATH=/`, the injected `<base href="/">` is identical to the placeholder in the source file. All relative paths resolve to `/js/api.js`, `/api/images`, etc. — identical to today's absolute paths. Zero behaviour change for root deployments.

## Testing

- Unit test: `root_path` config parses correctly and validates format.
- Integration test: `GET /` returns HTML containing `<base href="/custom/">` when `ROOT_PATH=/custom/`.
- Existing tests: all 144 passing tests must stay green (no backend logic changes).

## Out of Scope

- HTTPS termination (nginx's job)
- Multiple concurrent subpath mounts
- Non-nginx reverse proxies (same pattern works for any proxy that strips prefix)
