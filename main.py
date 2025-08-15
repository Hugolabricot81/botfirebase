# main.py
import asyncio
import discord
from discord.ext import commands, tasks
import firebase_admin
from firebase_admin import credentials, firestore
import requests
import re
import os

# --- CONFIG ---
DISCORD_TOKEN = os.environ.get("DISCORD_TOKEN")
FIREBASE_KEY_PATH = "/etc/secrets/serviceAccountKey.json"  # chemin du secret file sur Render

# --- INIT FIREBASE ---
cred = credentials.Certificate(FIREBASE_KEY_PATH)
firebase_admin.initialize_app(cred)
db = firestore.client()

# --- INIT BOT ---
intents = discord.Intents.default()
intents.message_content = True  # nécessaire pour lire le contenu des messages si tu en as besoin
bot = commands.Bot(command_prefix='!', intents=intents)

# --- SCRAPING CLUB ---
def scrape_club(club_tag):
    """Retourne la liste des joueurs d'un club avec pseudo, id et trophées."""
    clean_tag = club_tag.replace('#', '').upper()
    url = f'https://brawlace.com/clubs/%23{clean_tag}'
    response = requests.get(url)
    html = response.text

    tr_regex = re.compile(r'<tr[^>]*>([\s\S]*?)</tr>', re.IGNORECASE)
    td_regex = re.compile(r'<td[^>]*>([\s\S]*?)</td>', re.IGNORECASE)

    result = []
    for tr_match in tr_regex.finditer(html):
        tds = [td.strip() for td in td_regex.findall(tr_match.group(1))]
        if len(tds) >= 4:
            # Pseudo
            pseudo_match = re.search(r'<a[^>]*>(.*?)</a>', tds[1])
            pseudo = pseudo_match.group(1).strip() if pseudo_match else re.sub(r'<[^>]+>', '', tds[1]).strip()
            # ID
            id_match = re.search(r'data-bs-player-tag=[\'"](#.*?)["\']', tds[1])
            player_id = id_match.group(1).strip() if id_match else ""
            # Trophées actuels
            trophies = int(re.sub(r'[^\d]', '', tds[3]))
            result.append({
                "pseudo": pseudo,
                "id": player_id,
                "trophies": trophies
            })
    return result

# --- FIREBASE UPDATE ---
def update_firebase(club_tag):
    players = scrape_club(club_tag)
    for player in players:
        doc_ref = db.collection("players").document(player["id"])
        doc_ref.set({
            "pseudo": player["pseudo"],
            "id": player["id"],
            "trophées_actuels": player["trophies"],
            "club": club_tag,
            "updatedAt": firestore.SERVER_TIMESTAMP
        }, merge=True)  # merge=True pour ne pas écraser le document entier

# --- COMMANDES ---
@bot.slash_command(name="update", description="Met à jour les joueurs du club")
async def update(ctx, club_tag: str):
    await ctx.respond(f"Mise à jour du club {club_tag}...")
    update_firebase(club_tag)
    await ctx.send(f"Club {club_tag} mis à jour dans Firebase !")

# --- TÂCHE AUTOMATIQUE (OPTIONNELLE) ---
# @tasks.loop(hours=1)
# async def auto_update():
#     update_firebase("TON_CLUB_TAG")

# --- RUN BOT ---
if __name__ == "__main__":
    bot.run(DISCORD_TOKEN)
