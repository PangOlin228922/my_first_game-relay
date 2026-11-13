FROM python:3.12-slim
WORKDIR /app
# Force Cache Bust - Update 2.0: Developer Player DB & Web Dashboard
COPY relay_server.py /app/relay_server.py
COPY players_db.json /app/players_db.json
ENV PORT=25569
EXPOSE 25569
CMD ["python", "-u", "/app/relay_server.py"]
