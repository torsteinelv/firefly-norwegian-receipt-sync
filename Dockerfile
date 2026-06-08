FROM python:3.14-slim
WORKDIR /app
COPY requirements.txt requirements.txt
COPY sync.py sync.py
COPY trumf.py trumf.py
COPY classifier.py classifier.py
RUN pip install --no-cache-dir -r requirements.txt
CMD ["python", "-u", "sync.py"]
