# Utiliser une image Python
FROM python:3.11-slim

# Créer un dossier de travail
WORKDIR /app

# Copier les fichiers
COPY requirements.txt .
COPY main.py .
COPY serviceAccountKey.json .

# Installer les dépendances
RUN pip install --no-cache-dir -r requirements.txt

# Exposer le port pour Render
EXPOSE 8080

# Lancer le bot
CMD ["python", "main.py"]
