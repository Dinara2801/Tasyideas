FROM python:3.9
WORKDIR /app

COPY backend/requirements.txt ./requirements.txt

RUN pip install -r requirements.txt --no-cache-dir

COPY backend/. .

COPY data/ ./data/

CMD ["gunicorn", "--bind", "0.0.0.0:8000", "foodgram_backend.wsgi"]
