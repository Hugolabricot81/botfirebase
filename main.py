import discord
from discord.ext import commands, tasks
import asyncio
import aiohttp
import re
import json
import os
from datetime import datetime, timezone
import logging
from flask import Flask
import threading
import time

# Firebase imports
import firebase_admin
from firebase_admin import credentials, firestore

# Configuration du logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class BrawlStarsBot:
    def __init__(self):
        # Initialisation Discord
        intents = discord.Intents.default()
        intents.message_content = True
        self.bot = commands.Bot(command_prefix='!', intents=intents)
        
        # Initialisation Firebase
        self.init_firebase()
        
        # Configuration des clubs (à modifier selon vos clubs)
        self.clubs = {
            "Club1": "#2YGPRQYCC",  # Remplacez par vos vrais tags de clubs
            "Club2": "#AUTRE_TAG",
        }
        
        # Flask pour le ping d'Uptime Robot
        self.app = Flask(__name__)
        
        self.setup_discord_events()
        self.setup_flask_routes()
        
    def init_firebase(self):
        """Initialise Firebase avec le secret file"""
        try:
            # Lire la clé Firebase depuis le secret file
            with open('/etc/secrets/FIREBASE_KEY', 'r') as f:
                firebase_key = json.load(f)
            
            cred = credentials.Certificate(firebase_key)
            firebase_admin.initialize_app(cred)
            self.db = firestore.client()
            logger.info("Firebase initialisé avec succès")
        except Exception as e:
            logger.error(f"Erreur lors de l'initialisation Firebase: {e}")
            raise
    
    def setup_flask_routes(self):
        """Configure les routes Flask pour le ping"""
        @self.app.route('/')
        def health_check():
            return "Bot is running!", 200
        
        @self.app.route('/ping')
        def ping():
            return "pong", 200
    
    def setup_discord_events(self):
        """Configure les événements Discord"""
        
        @self.bot.event
        async def on_ready():
            logger.info(f'{self.bot.user} est connecté!')
            try:
                synced = await self.bot.tree.sync()
                logger.info(f"Synchronisé {len(synced)} commande(s)")
            except Exception as e:
                logger.error(f"Erreur lors de la synchronisation: {e}")
            
            # Démarrer la mise à jour automatique
            self.auto_update.start()
        
        @self.bot.tree.command(name="mytrophy", description="Affiche vos trophées actuels")
        async def mytrophy(interaction: discord.Interaction, player_id: str):
            await interaction.response.defer()
            
            try:
                # Nettoyer l'ID du joueur
                clean_id = player_id.replace('#', '').upper()
                if not clean_id.startswith('#'):
                    clean_id = '#' + clean_id
                
                # Chercher le joueur dans Firestore
                players_ref = self.db.collection('players')
                query = players_ref.where('id', '==', clean_id).limit(1)
                docs = query.stream()
                
                player_doc = None
                for doc in docs:
                    player_doc = doc.to_dict()
                    break
                
                if not player_doc:
                    await interaction.followup.send(f"Joueur {clean_id} non trouvé dans la base de données.")
                    return
                
                embed = discord.Embed(
                    title=f"🏆 Trophées de {player_doc['pseudo']}",
                    color=0x00ff00
                )
                embed.add_field(name="Trophées actuels", value=f"{player_doc['trophees_actuels']:,}", inline=True)
                embed.add_field(name="Trophées début mois", value=f"{player_doc['trophees_debut_mois']:,}", inline=True)
                
                diff = player_doc['trophees_actuels'] - player_doc['trophees_debut_mois']
                diff_emoji = "📈" if diff > 0 else "📉" if diff < 0 else "➖"
                embed.add_field(name="Différence", value=f"{diff_emoji} {diff:+,}", inline=True)
                
                embed.add_field(name="Club", value=player_doc['club'], inline=True)
                
                if 'updatedAt' in player_doc:
                    last_update = player_doc['updatedAt']
                    embed.set_footer(text=f"Dernière mise à jour: {last_update.strftime('%d/%m/%Y %H:%M')}")
                
                await interaction.followup.send(embed=embed)
                
            except Exception as e:
                logger.error(f"Erreur dans mytrophy: {e}")
                await interaction.followup.send("Une erreur s'est produite lors de la récupération des données.")
        
        @self.bot.tree.command(name="update", description="Met à jour tous les joueurs d'un club")
        async def update_club(interaction: discord.Interaction, club_name: str):
            await interaction.response.defer()
            
            if club_name not in self.clubs:
                available_clubs = ", ".join(self.clubs.keys())
                await interaction.followup.send(f"Club '{club_name}' non trouvé. Clubs disponibles: {available_clubs}")
                return
            
            try:
                club_tag = self.clubs[club_name]
                updated_count = await self.scrape_and_update_club(club_tag, club_name)
                
                embed = discord.Embed(
                    title="✅ Mise à jour terminée",
                    description=f"Club: {club_name}\nJoueurs mis à jour: {updated_count}",
                    color=0x00ff00
                )
                await interaction.followup.send(embed=embed)
                
            except Exception as e:
                logger.error(f"Erreur dans update_club: {e}")
                await interaction.followup.send("Une erreur s'est produite lors de la mise à jour.")
        
        @self.bot.tree.command(name="meilleur_rusheur", description="Affiche le meilleur rusheur de chaque club")
        async def meilleur_rusheur(interaction: discord.Interaction):
            await interaction.response.defer()
            
            try:
                embed = discord.Embed(
                    title="🚀 Meilleurs rusheurs du mois",
                    color=0xffd700
                )
                
                for club_name in self.clubs.keys():
                    best_player = await self.get_best_rusher(club_name)
                    if best_player:
                        diff = best_player['trophees_actuels'] - best_player['trophees_debut_mois']
                        embed.add_field(
                            name=f"🏆 {club_name}",
                            value=f"**{best_player['pseudo']}**\n+{diff:,} trophées",
                            inline=True
                        )
                    else:
                        embed.add_field(
                            name=f"❌ {club_name}",
                            value="Aucun joueur trouvé",
                            inline=True
                        )
                
                await interaction.followup.send(embed=embed)
                
            except Exception as e:
                logger.error(f"Erreur dans meilleur_rusheur: {e}")
                await interaction.followup.send("Une erreur s'est produite lors de la récupération des données.")
    
    async def scrape_club_data(self, club_tag):
        """Scrape les données d'un club depuis brawlace.com"""
        try:
            clean_tag = club_tag.replace('#', '').upper()
            url = f'https://brawlace.com/clubs/%23{clean_tag}'
            
            async with aiohttp.ClientSession() as session:
                async with session.get(url) as response:
                    if response.status != 200:
                        logger.error(f"Erreur HTTP {response.status} pour {url}")
                        return []
                    
                    html = await response.text()
            
            # Parser le HTML pour extraire les données des joueurs
            tr_pattern = re.compile(r'<tr[^>]*>([\s\S]*?)</tr>', re.IGNORECASE)
            td_pattern = re.compile(r'<td[^>]*>([\s\S]*?)</td>', re.IGNORECASE)
            
            players = []
            
            for tr_match in tr_pattern.finditer(html):
                tr_content = tr_match.group(1)
                tds = [td_match.group(1).strip() for td_match in td_pattern.finditer(tr_content)]
                
                if len(tds) >= 4:
                    # Extraire le pseudo
                    pseudo_match = re.search(r'<a[^>]*>(.*?)</a>', tds[1])
                    pseudo = pseudo_match.group(1) if pseudo_match else ""
                    
                    # Extraire l'ID du joueur
                    id_match = re.search(r'data-bs-player-tag=[\'"]([^\'""]*)[\'"]', tds[1])
                    player_id = id_match.group(1) if id_match else ""
                    
                    # Extraire les trophées
                    trophy_match = re.search(r'<font[^>]*>([^<]+)</font>', tds[3])
                    if not trophy_match:
                        trophy_match = re.search(r'>([^<]+)<', tds[3])
                    
                    if trophy_match:
                        trophies_str = trophy_match.group(1).strip().replace(',', '')
                        try:
                            trophies = int(trophies_str)
                        except ValueError:
                            continue
                    else:
                        continue
                    
                    if pseudo and player_id and trophies:
                        players.append({
                            'pseudo': pseudo.strip(),
                            'id': player_id.strip(),
                            'trophies': trophies
                        })
            
            logger.info(f"Scrapé {len(players)} joueurs pour le club {club_tag}")
            return players
            
        except Exception as e:
            logger.error(f"Erreur lors du scraping de {club_tag}: {e}")
            return []
    
    async def scrape_and_update_club(self, club_tag, club_name):
        """Scrape et met à jour les données d'un club dans Firebase"""
        players_data = await self.scrape_club_data(club_tag)
        updated_count = 0
        
        for player_data in players_data:
            try:
                player_ref = self.db.collection('players').document(player_data['id'])
                player_doc = player_ref.get()
                
                current_time = datetime.now(timezone.utc)
                
                if player_doc.exists:
                    # Mettre à jour le joueur existant
                    update_data = {
                        'pseudo': player_data['pseudo'],
                        'trophees_actuels': player_data['trophies'],
                        'club': club_name,
                        'updatedAt': current_time
                    }
                    player_ref.update(update_data)
                else:
                    # Créer un nouveau joueur
                    new_player_data = {
                        'pseudo': player_data['pseudo'],
                        'id': player_data['id'],
                        'trophees_debut_mois': player_data['trophies'],
                        'trophees_actuels': player_data['trophies'],
                        'club': club_name,
                        'updatedAt': current_time
                    }
                    player_ref.set(new_player_data)
                
                updated_count += 1
                
            except Exception as e:
                logger.error(f"Erreur lors de la mise à jour du joueur {player_data['id']}: {e}")
        
        logger.info(f"Mis à jour {updated_count} joueurs pour {club_name}")
        return updated_count
    
    async def get_best_rusher(self, club_name):
        """Trouve le meilleur rusheur d'un club"""
        try:
            players_ref = self.db.collection('players')
            query = players_ref.where('club', '==', club_name)
            docs = query.stream()
            
            best_player = None
            best_diff = -float('inf')
            
            for doc in docs:
                player_data = doc.to_dict()
                diff = player_data['trophees_actuels'] - player_data['trophees_debut_mois']
                
                if diff > best_diff:
                    best_diff = diff
                    best_player = player_data
            
            return best_player
            
        except Exception as e:
            logger.error(f"Erreur lors de la recherche du meilleur rusheur pour {club_name}: {e}")
            return None
    
    @tasks.loop(seconds=30)
    async def auto_update(self):
        """Met à jour automatiquement tous les clubs toutes les 30 secondes"""
        logger.info("Début de la mise à jour automatique")
        
        for club_name, club_tag in self.clubs.items():
            try:
                await self.scrape_and_update_club(club_tag, club_name)
                await asyncio.sleep(2)  # Petite pause entre chaque club
            except Exception as e:
                logger.error(f"Erreur lors de la mise à jour automatique de {club_name}: {e}")
    
    def run_flask(self):
        """Lance le serveur Flask"""
        self.app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)), debug=False)
    
    async def run_bot(self):
        """Lance le bot Discord"""
        token = os.environ.get('DISCORD_TOKEN')
        if not token:
            raise ValueError("DISCORD_TOKEN non trouvé dans les variables d'environnement")
        
        await self.bot.start(token)
    
    def run(self):
        """Lance le bot et le serveur Flask"""
        # Lancer Flask dans un thread séparé
        flask_thread = threading.Thread(target=self.run_flask, daemon=True)
        flask_thread.start()
        
        # Lancer le bot Discord
        asyncio.run(self.run_bot())

if __name__ == "__main__":
    bot = BrawlStarsBot()
    bot.run()
