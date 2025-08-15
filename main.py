import os
import discord
from discord.ext import commands, tasks
from discord import app_commands
import firebase_admin
from firebase_admin import credentials, firestore
from flask import Flask
import gspread
from oauth2client.service_account import ServiceAccountCredentials

# ---------------- Firebase ----------------
FIREBASE_KEY_PATH = "serviceAccountKey.json"
cred = credentials.Certificate(FIREBASE_KEY_PATH)
firebase_admin.initialize_app(cred)
db = firestore.client()

# ---------------- Google Sheets ----------------
# Accès aux deux feuilles "DébutMois" et "clubstr"
scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
creds_sheets = ServiceAccountCredentials.from_json_keyfile_name(FIREBASE_KEY_PATH, scope)
client_sheets = gspread.authorize(creds_sheets)

# ID de ton Google Sheets (dans l'URL)
SPREADSHEET_ID = os.environ.get("SPREADSHEET_ID")

sheet_debut = client_sheets.open_by_key(SPREADSHEET_ID).worksheet("DébutMois")
sheet_actuel = client_sheets.open_by_key(SPREADSHEET_ID).worksheet("clubstr")

# ---------------- Discord ----------------
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="/", intents=intents)

# ---------------- Flask ----------------
app = Flask("")

@app.route("/")
def home():
    return "Bot en ligne !"

def run_flask():
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))

# ---------------- Fonction scraping ----------------
def get_all_players():
    clubs = [
        "Prairie fleurie",
        "Prairie celeste",
        "Prairie etoilee",
        "Prairie brulee",
        "Prairie gelée",
        "Mini prairie"
    ]

    players = []
    for club in clubs:
        # On récupère les colonnes : pseudo, tag, trophées
        data_debut = sheet_debut.get_all_values()
        data_actuel = sheet_actuel.get_all_values()

        # On suppose ici que les données sont dans des blocs de 3 colonnes pour chaque club
        # pseudo | tag | trophées
        # On filtre en fonction du nom du club (à adapter si la structure diffère)
        
        # ⚠ Ici on fait simple : on boucle sur toutes les lignes et on aligne début/actuel
        for i in range(len(data_debut)):
            pseudo_debut, tag_debut, trophees_debut = data_debut[i][0:3]
            pseudo_actuel, tag_actuel, trophees_actuel = data_actuel[i][0:3]

            if tag_debut == tag_actuel and tag_debut.strip() != "":
                players.append({
                    "pseudo": pseudo_debut,
                    "id": tag_debut,
                    "trophees_debut_mois": int(trophees_debut),
                    "trophees_actuels": int(trophees_actuel),
                    "club": club
                })
    return players

# ---------------- Commande slash ----------------
@bot.tree.command(name="update", description="Scrape Google Sheets et met à jour Firestore (sans colonnes Mega Pig)")
async def update(interaction: discord.Interaction):
    joueurs = get_all_players()

    for joueur in joueurs:
        doc_ref = db.collection("players").document(joueur["id"])
        joueur["updatedAt"] = firestore.SERVER_TIMESTAMP
        doc_ref.set(joueur)

    await interaction.response.send_message(f"✅ {len(joueurs)} joueurs mis à jour dans Firestore !")

# ---------------- Background task ----------------
@tasks.loop(hours=1)
async def update_task():
    joueurs = get_all_players()
    for joueur in joueurs:
        doc_ref = db.collection("players").document(joueur["id"])
        joueur["updatedAt"] = firestore.SERVER_TIMESTAMP
        doc_ref.set(joueur)
    print(f"[Auto-update] {len(joueurs)} joueurs mis à jour")

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
