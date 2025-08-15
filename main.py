import os
import discord
from discord.ext import commands, tasks
import asyncio
import firebase_admin
from firebase_admin import credentials, firestore
from datetime import datetime

# ====== CONFIGURATION FIREBASE ======
cred = credentials.Certificate("firebaseKey.json")  # Fichier de clé Firebase
firebase_admin.initialize_app(cred)
db = firestore.client()

# ====== CONFIGURATION DISCORD ======
TOKEN = os.environ.get("DISCORD_TOKEN")  # Ton token dans Render
CHANNEL_ID = 1402293997560401941  # ID du salon où poster le leaderboard
intents = discord.Intents.default()
bot = commands.Bot(command_prefix="/", intents=intents)

# ====== FONCTIONS FIREBASE ======

def save_scraped_data(club_name, players):
    """
    Enregistre les données scrapées dans Firestore.
    players: liste de dicts {pseudo, tag, trophies_start, trophies_now}
    """
    club_ref = db.collection("clubs").document(club_name)
    for player in players:
        club_ref.collection("players").document(player["tag"]).set(player)


def get_leaderboard(club_name):
    """
    Récupère et trie les joueurs d'un club selon leur gain de trophées.
    """
    players_ref = db.collection("clubs").document(club_name).collection("players").stream()
    players = [doc.to_dict() for doc in players_ref]
    players.sort(key=lambda x: x["trophies_now"] - x["trophies_start"], reverse=True)
    return players


def get_player(tag):
    """
    Récupère les infos d'un joueur par son tag (peu importe le club).
    """
    clubs_ref = db.collection("clubs").stream()
    for club in clubs_ref:
        players_ref = db.collection("clubs").document(club.id).collection("players").stream()
        for player in players_ref:
            data = player.to_dict()
            if data["tag"].lower() == tag.lower():
                return data
    return None

# ====== COMMANDES DISCORD ======

@bot.command(name="mytrophy")
async def mytrophy(ctx, tag: str):
    """Affiche les trophées actuels d'un joueur."""
    player = get_player(tag)
    if player:
        gain = player["trophies_now"] - player["trophies_start"]
        await ctx.send(f"🏆 **{player['pseudo']}**\n"
                       f"Trophées actuels : {player['trophies_now']}\n"
                       f"Gain ce mois-ci : {gain}")
    else:
        await ctx.send("❌ Joueur introuvable.")


@bot.command(name="leaderboard")
async def leaderboard(ctx):
    """Affiche le meilleur rusheur de chaque club."""
    clubs_ref = db.collection("clubs").stream()
    leaderboard_msg = "**🏆 Meilleurs rusheurs par club :**\n"
    for club in clubs_ref:
        players = get_leaderboard(club.id)
        if players:
            best = players[0]
            gain = best["trophies_now"] - best["trophies_start"]
            leaderboard_msg += f"**{club.id}** → {best['pseudo']} (+{gain} trophées)\n"
    await ctx.send(leaderboard_msg)

# ====== TÂCHE AUTOMATIQUE ======

@tasks.loop(hours=1)
async def auto_leaderboard():
    """Poste le leaderboard automatiquement toutes les heures."""
    channel = bot.get_channel(CHANNEL_ID)
    if channel:
        clubs_ref = db.collection("clubs").stream()
        leaderboard_msg = "**🏆 Meilleurs rusheurs par club :**\n"
        for club in clubs_ref:
            players = get_leaderboard(club.id)
            if players:
                best = players[0]
                gain = best["trophies_now"] - best["trophies_start"]
                leaderboard_msg += f"**{club.id}** → {best['pseudo']} (+{gain} trophées)\n"
        await channel.send(leaderboard_msg)

@bot.event
async def on_ready():
    print(f"✅ Connecté en tant que {bot.user}")
    auto_leaderboard.start()

# ====== LANCEMENT ======
bot.run(TOKEN)
