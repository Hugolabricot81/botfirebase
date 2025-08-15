import os
import discord
from discord.ext import commands, tasks
from discord import app_commands
import firebase_admin
from firebase_admin import credentials, firestore
from flask import Flask

# ---------------- Firebase ----------------
FIREBASE_KEY_PATH = "serviceAccountKey.json"  # nom exact du fichier dans ton repo
cred = credentials.Certificate(FIREBASE_KEY_PATH)
firebase_admin.initialize_app(cred)
db = firestore.client()

# ---------------- Discord ----------------
intents = discord.Intents.default()
intents.message_content = True  # pour lire le contenu des messages / slash commands
bot = commands.Bot(command_prefix="/", intents=intents)

# ---------------- Flask ----------------
app = Flask("")

@app.route("/")
def home():
    return "Bot en ligne !"

def run_flask():
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))

# ---------------- Commande slash ----------------
@bot.tree.command(name="update", description="Met à jour les joueurs dans Firestore (test)")
async def update(interaction: discord.Interaction):
    # Exemple de joueurs
    joueurs = [
        {
            "pseudo": "Hugo",
            "id": "12345",
            "trophees_debut_mois": 300,
            "trophees_actuels": 350,
            "club": "Prairie",
            "tickets_mega_pig": 10,
            "wins_pig": 5,
        },
        {
            "pseudo": "Alice",
            "id": "67890",
            "trophees_debut_mois": 250,
            "trophees_actuels": 280,
            "club": "MiniPrairie",
            "tickets_mega_pig": 7,
            "wins_pig": 3,
        }
    ]

    # Mise à jour Firestore
    for joueur in joueurs:
        doc_ref = db.collection("players").document(joueur["id"])
        joueur["updatedAt"] = firestore.SERVER_TIMESTAMP
        doc_ref.set(joueur)

    await interaction.response.send_message("✅ Firestore mis à jour !")

# ---------------- Background task (facultative) ----------------
@tasks.loop(minutes=30)
async def update_task():
    # Ici tu peux mettre le code pour scraper et mettre à jour automatiquement
    print("Update automatique tous les 30 min (simulation)")

@bot.event
async def on_ready():
    print(f"Connecté en tant que {bot.user}")
    try:
        synced = await bot.tree.sync()
        print(f"Synced {len(synced)} commandes slash")
    except Exception as e:
        print(f"Erreur sync slash commands : {e}")
    update_task.start()

# ---------------- Lancement ----------------
if __name__ == "__main__":
    import threading
    threading.Thread(target=run_flask).start()
    TOKEN = os.environ.get("DISCORD_TOKEN")
    bot.run(TOKEN)
