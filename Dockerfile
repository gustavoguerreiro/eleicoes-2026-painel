FROM python:3.12-slim
RUN useradd --create-home --uid 10001 app
WORKDIR /app
COPY backend/requirements.txt backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt
COPY --chown=app:app backend backend
COPY --chown=app:app frontend frontend
COPY --chown=app:app data data
RUN mkdir -p /app/logs && chown app:app /app/logs
USER app
ENV PYTHONUNBUFFERED=1 HOST=0.0.0.0 PORT=8765
EXPOSE 8765
# Modo público é o padrão (só o RN, sem chat). Atrás de nginx/Cloudflare: CONFIAR_PROXY=1 (veja o docker-compose.yml).
HEALTHCHECK --interval=30s --timeout=5s --start-period=40s CMD python -c "import urllib.request,os;urllib.request.urlopen('http://127.0.0.1:'+os.environ['PORT']+'/healthz',timeout=4)"
CMD ["python", "backend/painel_server.py", "--web"]
