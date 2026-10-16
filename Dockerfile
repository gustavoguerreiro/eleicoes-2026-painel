FROM python:3.12-slim
WORKDIR /app
COPY backend/requirements.txt backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt
COPY backend backend
COPY frontend frontend
COPY data data
ENV PYTHONUNBUFFERED=1 HOST=0.0.0.0 PORT=8765
EXPOSE 8765
# Atrás de Cloudflare/nginx: CONFIAR_PROXY=1 faz o limite do chat usar o IP real do visitante.
HEALTHCHECK --interval=30s --timeout=5s CMD python -c "import urllib.request,os;urllib.request.urlopen('http://127.0.0.1:'+os.environ['PORT']+'/healthz',timeout=4)"
CMD ["python", "backend/painel_server.py", "--web"]
