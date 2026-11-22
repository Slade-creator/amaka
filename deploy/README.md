# Deploying AMAKA

| Piece | Command (run from repo root unless noted) |
|---|---|
| Backend (AWS Lambda, eu-north-1) | `aws login` then `python deploy/deploy_backend.py` |
| Web frontend (Cloudflare Workers) | in `frontend/`: set `VITE_API_BASE_URL` to the Lambda URL, `npx vite build --outDir dist-web`, `npx wrangler deploy` |
| Android APK | put the Lambda URL in `frontend/.env.mobile.local`, `npm run apk` in `frontend/`, then `gh release create vX.Y.Z <apk>` |

Lambda function env vars (JWT secret, CORS origins, `/tmp` paths) are set once on the function and are not touched by the script.
Add a new web origin with `SENTINEL_ALLOWED_ORIGINS` (comma-separated).
Lambda's disk is read-only except `/tmp`, so accounts re-seed on cold start and ingested readings do not persist.
