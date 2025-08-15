# Dockerfile
FROM python:3.11-slim

WORKDIR /app

# Copier seulement le code et requirements
COPY requirements.txt .
COPY main.py .

# Installer les dépendances
RUN pip install --no-cache-dir -r requirements.txt

# Exposer le port utilisé par Flask
EXPOSE 8080

# Commande pour lancer le bot
CMD ["python", "main.py"]
