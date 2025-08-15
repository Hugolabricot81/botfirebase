import os
import discord
from discord.ext import commands, tasks
import firebase_admin
from firebase_admin import credentials, firestore
import aiohttp
from bs4 import BeautifulSoup
import re
from webserver import keep_alive
from datetime import datetime, timezone

# ---------- Config ----------
TOKEN = os.getenv("DISCORD_TOKEN")
FIREBASE_KEY_PATH = "serviceAccountKey.json"  # Render : secret file
CLUB_TAGS = ["#2YGPRQYCC", "#AAAAAAA"]       # Ajouter vos clubs
SCRAPE_URL_BASE = "https://brawlace.com/clubs/%23"

# ---------- Firebase ----------
cred = credentials.Certificate(FIREBASE_KEY_PATH)
firebase_admin.initialize_app(cred)
db = firestore.client()

# ---------- Discord Bot ----------
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

# ---------- Scraper ----------
async def scrape_club(club_tag):
    url = SCRAPE_URL_BASE + club_tag.replace("#", "")
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as resp:
            html = await resp.text()

    rows = re.findall(r"<tr[^>]*>(.*?)</tr>", html, re.S)
    membres = []

    for row in rows:
        cols = re.findall(r"<td.*?>(.*?)</td>", row, re.S)
        if len(cols) < 4:
            continue

        pseudo_match = re.search(r"<a[^>]*>(.*?)</a>", cols[1])
        pseudo = pseudo_match.group(1).strip() if pseudo_match else ""

        id_match = re.search(r"data-bs-player-tag=['\"](#.*?)['\"]", cols[1])
        player_id = id_match.group(1).strip() if id_match else ""

        try:
            troph_actuels = int(re.sub(r"[^\d]", "", cols[3]))
        except ValueError:
            troph_actuels = 0

        # Tickets et wins pig (à compléter selon HTML joueur)
        tickets = 0
        wins = 0

        membres.append({
            "pseudo": pseudo,
            "id": player_id,
            "trophées_début_mois": 0,
            "trophées_actuels": troph_actuels,
            "club": club_tag,
            "tickets_mega_pig": tickets,
            "wins_pig": wins,
            "updatedAt": datetime.now(timezone.utc)
        })

    return membres

async def update_firebase():
    for tag in CLUB_TAGS:
        membres = await scrape_club(tag)
        for membre in membres:
            db.collection("joueurs").document(membre["id"]).set(membre, merge=True)
    print("✅ Firebase mise à jour.")

# ---------- Tâche automatique ----------
@tasks.loop(minutes=30)
async def auto_update():
    await update_firebase()

@bot.event
async def on_ready():
    print(f"Bot connecté en tant que {bot.user}")
    auto_update.start()

# ---------- Commande manuelle ----------
@bot.tree.command(name="update", description="Met à jour la base Firebase manuellement")
async def update_command(interaction: discord.Interaction):
    await interaction.response.send_message("Mise à jour en cours...", ephemeral=True)
    await update_firebase()
    await interaction.followup.send("✅ Mise à jour terminée.")

# ---------- Serveur Flask ----------
keep_alive()

# ---------- Démarrage du bot ----------
bot.run(TOKEN)
