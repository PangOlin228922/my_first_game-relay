FROM python:3.12-slim
WORKDIR /app
COPY . /app/
ENV PORT=25569
EXPOSE 25569
CMD ["python", "-u", "/app/relay_server.py"]
