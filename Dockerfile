FROM python:3.12-slim

WORKDIR /project/web-forecast

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/project/web-forecast

COPY requirements.txt /project/requirements.txt

RUN pip install --no-cache-dir -r /project/requirements.txt

COPY web-forecast/app ./app

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]