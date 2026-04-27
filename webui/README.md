# Short_videoGEN WebUI

Local single-user control room for the existing Short_videoGEN CLI pipeline.

## Run

Backend:

```bash
pip install -r requirements.txt
uvicorn webui.backend.main:app --reload --host 127.0.0.1 --port 8000
```

Frontend:

```bash
cd webui/frontend
npm install
npm run dev
```

Open http://127.0.0.1:5173.

## Notes

- The WebUI keeps source artifacts on disk and uses SQLite only as an index.
- Existing CLI scripts remain directly runnable.
- Review runs are written under `test/webui_review_runs/`.
- `record` JSON is read-only in v1; user prompt changes are saved as review-run overrides.

