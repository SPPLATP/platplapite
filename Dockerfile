FROM python:3.11-slim  

WORKDIR /app  
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt  

COPY . .  

# Modificado para usar platpalpite.py
CMD ["gunicorn", "-b", "0.0.0.0:8080", "platpalpite:app"]  

EXPOSE 8080  