import discord
from discord.ext import commands, tasks
from discord import app_commands
import firebase_admin
from firebase_admin import credentials, firestore
from datetime import datetime, timezone

# -------------------------------
# CONFIG FIREBASE
# -------------------------------
FIREBASE_KEY_PATH = "serviceAccountKey.json"


cred = credentials.Certificate(FIREBASE_KEY_PATH)
firebase_admin.initialize_app(cred)
db = firestore.client()

# -------------------------------
# CONFIG DISCORD
# -------------------------------
TOKEN = "DISCORD_TOKEN"

intents = discord.Intents.default()
bot = commands.Bot(command_prefix="!", intents=intents)

# -------------------------------
# COMMANDE /UPDATE
# -------------------------------
@bot.tree.command(name="update", description="Met à jour Firebase avec des données test")
async def update(interaction: discord.Interaction):
    await interaction.response.send_message("🔄 Mise à jour Firebase test en cours...")

    # Données test
    test_players = [
        {
            "pseudo": "TestPlayer1",
            "id": "#TEST001",
            "trophées_début_mois": 1000,
            "trophées_actuels": 1050,
            "club": "#2YGPRQYCC",
            "tickets_mega_pig": 5,
            "wins_pig": 3,
            "updatedAt": datetime.now(timezone.utc)
        },
        {
            "pseudo": "TestPlayer2",
            "id": "#TEST002",
            "trophées_début_mois": 800,
            "trophées_actuels": 850,
            "club": "#2YGPRQYCC",
            "tickets_mega_pig": 2,
            "wins_pig": 1,
            "updatedAt": datetime.now(timezone.utc)
        }
    ]

    # Écriture dans Firestore
    for player in test_players:
        print(f"➡ Mise à jour de {player['pseudo']} (ID: {player['id']})")
        db.collection("players").document(player["id"]).set(player, merge=True)

    await interaction.followup.send("✅ Mise à jour test terminée !")
    print("✅ Mise à jour test terminée !")

# -------------------------------
# ON_READY
# -------------------------------
@bot.event
async def on_ready():
    await bot.tree.sync()
    print(f"{bot.user} est connecté et les slash commands sont synchronisées !")

# -------------------------------
# LANCEMENT DU BOT
# -------------------------------
bot.run(TOKEN)
