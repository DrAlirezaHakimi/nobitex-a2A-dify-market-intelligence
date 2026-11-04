FROM python:3.12-slim
WORKDIR /srv
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app
COPY dashboard ./dashboard
EXPOSE 8000 8001
CMD ["python", "-m", "app.docker_main"]
