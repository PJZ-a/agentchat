FROM python:3.11-slim

WORKDIR /app

COPY agent-social-network-skill/scripts/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY agent-social-network-skill/scripts/relay_server.py .

EXPOSE 9527

CMD ["python", "relay_server.py", "--host", "0.0.0.0", "--port", "9527"]
