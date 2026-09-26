# FastAPI backend

Текущий интеграционный слой загружает `;`-CSV прогноза один раз при старте и отдаёт DTO, используемые корневым `frontend/`. Это read-only адаптер для стыковки; целевое PostgreSQL-хранилище и атомарный импорт остаются отдельными DEV-03/04.

## Запуск из корня MTTECH

```powershell
$env:FORECAST_CSV_PATH="MT-Hackathon-2026/data/test_submission.csv"
python -m uvicorn app.main:app --app-dir web-forecast --host 127.0.0.1 --port 8000
```

В другом терминале:

```powershell
cd frontend
$env:VITE_DATA_SOURCE="api"
$env:VITE_API_BASE_URL="http://127.0.0.1:8000"
npm run dev
```

Проверка backend:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/health
Invoke-RestMethod http://127.0.0.1:8000/api/forecast/runs
```

Если `FORECAST_CSV_PATH` не задан, сначала проверяется `data/processed/forecast.csv`, затем доступный только в текущем workspace development submission. В production путь должен задаваться явно. Разрешённые frontend origins настраиваются через `CORS_ORIGINS`.
