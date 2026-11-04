FROM python:3.12-slim
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
COPY requirements.txt requirements-radio.txt ./
RUN pip install --no-cache-dir -r requirements.txt
# Uncomment next line for optional BL .h5/.fil radio telescope input support:
# RUN pip install --no-cache-dir -r requirements-radio.txt
COPY signalwatch ./signalwatch
COPY static ./static
RUN mkdir -p /app/data/inbox
EXPOSE 8765
CMD ["uvicorn","signalwatch.app:app","--host","0.0.0.0","--port","8765","--workers","1"]
