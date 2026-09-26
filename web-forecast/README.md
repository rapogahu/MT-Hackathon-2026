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
npm run dev
```

В development frontend вызывает относительный `/api`, а Vite проксирует его на
`http://127.0.0.1:8000`. Это исключает зависимость браузера от CORS и случайно
сохранённого `VITE_API_BASE_URL`. Порт `5173` фиксирован: второй Vite не будет
молча запущен на другом порту.

Проверка backend:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/health
Invoke-RestMethod http://127.0.0.1:8000/api/forecast/runs
```

Если `FORECAST_CSV_PATH` не задан, сначала проверяется `data/processed/forecast.csv`, затем доступный только в текущем workspace development submission. В production путь должен задаваться явно. Разрешённые frontend origins настраиваются через `CORS_ORIGINS`. Для локальной разработки `CORS_ORIGIN_REGEX` по умолчанию разрешает loopback-адреса на любом порту, поэтому автоматический переход Vite с занятого `5173` на следующий порт не разрывает соединение с API.
