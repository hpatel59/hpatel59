FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
ENV DATA_DIR=/data PORT=8000
VOLUME ["/data"]
EXPOSE 8000
# marking can take up to a minute, so allow long requests
CMD ["sh", "-c", "gunicorn -w 2 --threads 8 --timeout 180 -b 0.0.0.0:${PORT} server:app"]
