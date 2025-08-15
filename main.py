import discord
from discord import app_commands
import asyncio
import firebase_admin
from firebase_admin import credentials, firestore
from flask import Flask
import threading
import requests
import os
import re

# Lire le JSON depuis la variable d'environnement FIREBASE_KEY_JSON
firebase_json = os.environ.get("FIREBASE_KEY_JSON")
if not firebase_json:
    raise ValueError("La variable d'environnement FIREBASE_KEY_JSON n'existe pas")

# Convertir la chaîne JSON en dict
cred_dict = json.loads(firebase_json)

cred = credentials.Certificate(FIREBASE_KEY_PATH)
firebase_admin.initialize_app(cred)

db = firestore.client()


# -------------------------------
# SCRAPING FONCTION
# -------------------------------
def scrape_club(club_tag):
    """Scrape les joueurs d’un club depuis Brawlace"""
    url = f"https://brawlace.com/clubs/%23{club_tag.replace('#','').upper()}"
    response = requests.get(url)
    html = response.text

    tr_regex = re.compile(r"<tr[^>]*>([\s\S]*?)<\/tr>", re.IGNORECASE)
    td_regex = re.compile(r"<td[^>]*>([\s\S]*?)<\/td>", re.IGNORECASE)

    result = []

    for tr_match in tr_regex.findall(html):
        tds = td_regex.findall(tr_match)
        if len(tds) >= 4:
            pseudo_match = re.search(r"<a[^>]*>(.*?)<\/a>", tds[1])
            pseudo = pseudo_match.group(1).strip() if pseudo_match else tds[1].strip()

            id_match = re.search(r'data-bs-player-tag=["\'](#.*?)["\']', tds[1])
            player_id = id_match.group(1) if id_match else ""

            trophies = int(re.sub(r"[^\d]", "", tds[3]))

            result.append({
                "pseudo": pseudo,
                "id": player_id,
                "trophies": trophies
            })

    return result

# -------------------------------
# FIREBASE UPDATE
# -------------------------------
def update_firebase(club_tag):
    """Met à jour les joueurs dans Firestore"""
    players = scrape_club(club_tag)
    for player in players:
        doc_ref = db.collection("players").document(player["id"])
        doc_ref.set({
            "pseudo": player["pseudo"],
            "id": player["id"],
            "trophies": player["trophies"],
            "club": club_tag
        }, merge=True)

# -------------------------------
# DISCORD BOT
# -------------------------------
class MyClient(discord.Client):
    def __init__(self, *, intents: discord.Intents):
        super().__init__(intents=intents)
        self.tree = app_commands.CommandTree(self)

    async def setup_hook(self):
        await self.tree.sync()

intents = discord.Intents.default()
intents.message_content = True
client = MyClient(intents=intents)

@client.tree.command(name="update", description="Met à jour les joueurs du club")
async def update(interaction: discord.Interaction, club_tag: str):
    await interaction.response.send_message(f"Mise à jour du club {club_tag}...")
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, update_firebase, club_tag)
    await interaction.followup.send(f"Club {club_tag} mis à jour dans Firebase !")

# -------------------------------
# FLASK SERVER POUR PING
# -------------------------------
app = Flask("")

@app.route("/")
def home():
    return "Bot en ligne !"

def run():
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))

# Démarrage du serveur Flask dans un thread
threading.Thread(target=run).start()

# -------------------------------
# RUN BOT
# -------------------------------
client.run(DISCORD_TOKEN)
