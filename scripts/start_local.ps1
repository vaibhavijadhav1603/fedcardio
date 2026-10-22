# Start FedCardio on localhost: backend http://127.0.0.1:8000 (API docs /docs), frontend http://localhost:3000
# First run: python -m venv .venv; .venv\Scripts\pip install -r requirements.lock -r backend\requirements.txt;
#            .venv\Scripts\python -m fl_engine.data.download; .venv\Scripts\python -m backend.app.seed; cd frontend; npm install
$root = Split-Path -Parent $PSScriptRoot
Start-Process powershell -ArgumentList '-NoExit', '-Command', "cd '$root'; .venv\Scripts\python -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000"
Start-Process powershell -ArgumentList '-NoExit', '-Command', "cd '$root\frontend'; npx next dev -p 3000"
Start-Sleep -Seconds 8
Start-Process "http://localhost:3000"
