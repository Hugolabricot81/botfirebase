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
        
        # Configuration des clubs
        self.clubs = {
            "Prairie Fleurie": "#2C9Y28JPP",
            "Prairie Céleste": "#2JUVYQ0YV",
            "Prairie Gelée": "#2CJJLLUQ9",
            "Prairie étoilée": "#29UPLG8QQ",
            "Prairie Brulée": "#2YGPRQYCC",
            "Mini Prairie": "#JY89VGGP",
        }
        
        # Flask pour le ping d'Uptime Robot
        self.app = Flask(__name__)
        
        # Variable pour stocker le dernier message des rusheurs
        self.last_rusheur_message = None
        self.rusheur_channel_id = None  # À configurer via une commande
        
        # ID du rôle Modo
        self.MODO_ROLE_ID = 1185678999335219311
        
        self.setup_discord_events()
        self.setup_flask_routes()
    
    def has_modo_role(self, interaction: discord.Interaction) -> bool:
        """Vérifie si l'utilisateur a le rôle Modo"""
        if not interaction.guild:
            return False
        
        member = interaction.guild.get_member(interaction.user.id)
        if not member:
            return False
        
        return any(role.id == self.MODO_ROLE_ID for role in member.roles)
        
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
            logger.info("Mise à jour automatique programmée toutes les heures")
            
            # Démarrer l'envoi automatique des meilleurs rusheurs
            self.auto_rusheur_update.start()
            logger.info("Envoi automatique des meilleurs rusheurs programmé toutes les demi-heures")
        
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
            # Vérification du rôle Modo
            if not self.has_modo_role(interaction):
                embed = discord.Embed(
                    title="🚫 Accès refusé",
                    description="Cette commande est réservée aux membres ayant le rôle **Modo 🪻**.",
                    color=0xff0000
                )
                await interaction.response.send_message(embed=embed, ephemeral=True)
                return
                
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
                    description=f"Club: **{club_name}**\nJoueurs mis à jour: **{updated_count}**",
                    color=0x00ff00
                )
                embed.add_field(
                    name="ℹ️ Information",
                    value="Seuls les trophées actuels ont été mis à jour.\nLes trophées de début de mois sont préservés.",
                    inline=False
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
        
        @self.bot.tree.command(name="reset_debut_mois", description="Remet à jour les trophées de début de mois pour un club")
        async def reset_debut_mois(interaction: discord.Interaction, club_name: str):
            await interaction.response.defer()
            
            if club_name not in self.clubs:
                available_clubs = ", ".join(self.clubs.keys())
                await interaction.followup.send(f"Club '{club_name}' non trouvé. Clubs disponibles: {available_clubs}")
                return
            
            try:
                # Récupérer tous les joueurs du club
                players_ref = self.db.collection('players')
                query = players_ref.where('club', '==', club_name)
                docs = query.stream()
                
                updated_count = 0
                current_time = datetime.now(timezone.utc)
                
                for doc in docs:
                    player_data = doc.to_dict()
                    
                    # Mettre à jour trophees_debut_mois avec trophees_actuels
                    doc.reference.update({
                        'trophees_debut_mois': player_data['trophees_actuels'],
                        'updatedAt': current_time
                    })
                    updated_count += 1
                
                embed = discord.Embed(
                    title="🔄 Réinitialisation terminée",
                    description=f"Club: **{club_name}**\nJoueurs mis à jour: **{updated_count}**",
                    color=0x00ff00
                )
                embed.add_field(
                    name="Action effectuée",
                    value="Les trophées de début de mois ont été remis à jour avec les trophées actuels",
                    inline=False
                )
                embed.set_footer(text=f"Réinitialisé le {current_time.strftime('%d/%m/%Y à %H:%M')}")
                
                await interaction.followup.send(embed=embed)
                logger.info(f"Reset début mois effectué pour {club_name}: {updated_count} joueurs mis à jour")
                
            except Exception as e:
                logger.error(f"Erreur dans reset_debut_mois: {e}")
                await interaction.followup.send("Une erreur s'est produite lors de la réinitialisation.")
        
        @self.bot.tree.command(name="places_libres", description="Affiche le nombre de places libres dans chaque club")
        async def places_libres(interaction: discord.Interaction):
            # Vérification du rôle Modo
            if not self.has_modo_role(interaction):
                embed = discord.Embed(
                    title="🚫 Accès refusé",
                    description="Cette commande est réservée aux membres ayant le rôle **Modo 🪻**.",
                    color=0xff0000
                )
                await interaction.response.send_message(embed=embed, ephemeral=True)
                return
                
            await interaction.response.defer()
            
            try:
                embed = discord.Embed(
                    title="🌸 Places libres - Réseau Prairie",
                    description="Nombre de places disponibles dans chaque club",
                    color=0x2ecc71
                )
                
                total_places_libres = 0
                total_members = 0
                
                for club_name, club_tag in self.clubs.items():
                    club_ref = self.db.collection('clubs').document(club_tag)
                    club_doc = club_ref.get()
                    
                    if club_doc.exists:
                        club_data = club_doc.to_dict()
                        members = club_data.get('member_count', 0)
                        places_libres = 30 - members
                        
                        total_members += members
                        total_places_libres += places_libres
                        
                        # Emoji selon le nombre de places
                        if places_libres == 0:
                            emoji = "🔴"  # Complet
                        elif places_libres <= 5:
                            emoji = "🟡"  # Presque plein
                        else:
                            emoji = "🟢"  # Places disponibles
                        
                        embed.add_field(
                            name=f"{emoji} {club_name}",
                            value=f"**{places_libres}** place(s) libre(s)\n({members}/30 membres)",
                            inline=True
                        )
                    else:
                        embed.add_field(
                            name=f"❓ {club_name}",
                            value="Données non disponibles",
                            inline=True
                        )
                
                # Résumé total
                embed.add_field(
                    name="📊 Total Réseau Prairie",
                    value=f"🟢 **{total_places_libres}** places libres au total\n👥 **{total_members}/180** membres",
                    inline=False
                )
                
                # Légende
                embed.add_field(
                    name="🔍 Légende",
                    value="🔴 Complet • 🟡 Presque plein (≤5 places) • 🟢 Places disponibles",
                    inline=False
                )
                
                # Footer avec dernière mise à jour
                embed.set_footer(text="💡 Les données sont mises à jour toutes les heures")
                
                await interaction.followup.send(embed=embed)
                
            except Exception as e:
                logger.error(f"Erreur dans places_libres: {e}")
                await interaction.followup.send("Une erreur s'est produite lors de la récupération des places libres.")
        
        @self.bot.tree.command(name="presentation", description="Affiche la présentation du réseau Prairie avec les trophées actuels")
        async def presentation(interaction: discord.Interaction):
            # Vérification du rôle Modo
            if not self.has_modo_role(interaction):
                embed = discord.Embed(
                    title="🚫 Accès refusé",
                    description="Cette commande est réservée aux membres ayant le rôle **Modo 🪻**.",
                    color=0xff0000
                )
                await interaction.response.send_message(embed=embed, ephemeral=True)
                return
                
            await interaction.response.defer()
            
            try:
                # Mapping des clubs avec leurs emojis et seuils
                clubs_info = {
                    "Prairie Fleurie": {"emoji": "🌸", "seuil": "60k", "tag": "#2C9Y28JPP"},
                    "Prairie Céleste": {"emoji": "🪽", "seuil": "60k", "tag": "#2JUVYQ0YV"},
                    "Prairie Gelée": {"emoji": "❄️", "seuil": "60k", "tag": "#2CJJLLUQ9"},
                    "Prairie étoilée": {"emoji": "⭐️", "seuil": "55k", "tag": "#29UPLG8QQ"},
                    "Prairie Brulée": {"emoji": "🔥", "seuil": "45k", "tag": "#2YGPRQYCC"},
                    "Mini Prairie": {"emoji": "🧚", "seuil": "3k", "tag": "#JY89VGGP", "note": " (Club pour les smurfs)"}
                }
                
                # Récupérer les trophées de chaque club
                clubs_text = []
                
                for club_name, info in clubs_info.items():
                    club_ref = self.db.collection('clubs').document(info['tag'])
                    club_doc = club_ref.get()
                    
                    if club_doc.exists:
                        club_data = club_doc.to_dict()
                        total_trophies = club_data.get('total_trophies', 0)
                        
                        # Convertir en millions et arrondir au centième
                        if total_trophies >= 1000000:
                            trophies_display = f"{total_trophies / 1000000:.2f}M"
                        else:
                            trophies_display = f"{total_trophies / 1000:.0f}k"
                        
                        note = info.get('note', '')
                        clubs_text.append(f"{club_name} {info['emoji']} {trophies_display} 🏆 : À partir de {info['seuil']}.{note}")
                    else:
                        clubs_text.append(f"{club_name} {info['emoji']} ?.??M 🏆 : À partir de {info['seuil']}. (données non disponibles)")
                
                # Construire le texte complet
                presentation_text = f"""Bonjour à toutes et à tous ! 🌱🌸
Nous sommes une famille de 6 clubs, laissez-nous vous les présenter :
{chr(10).join(clubs_text)}
- Nous avons un Discord actif où l'on priorise entraide et convivialité entre tous. Vous pourrez y passer de bons moments et également lors de nos futurs projets d'animation (mini jeux bs 🏆 rush pig entre clubs 🐷 activées diverses et variées ex : gartic phone, among us 👾)
- Vous devrez vous montrer actif sur Brawl Stars et si vous l'êtes aussi sur le discord ça sera plus qu'apprécié ✅🐷 L'activité en mega pig est surveillée, un minimum est fixée (infos sur notre Discord). Toutes les méga pigs sont à 5/5 en fin d'événement ! 🐷
- On ne vous vire pas si vous êtes le dernier du club. Nous fixons des objectifs de trophées à atteindre par saison, qui sont différents selon les clubs et qui peuvent être adaptés à chaque membre. Nous sommes flexibles et compréhensifs tant qu'il y a un minimum d'activité sur Brawl Stars 🌱✨
• Rejoignez notre grande et belle famille dans laquelle vous pourrez push les TR 🏆 et la Ranked 💎, tout en passant de bons moments ! 🌱🌸
--
(MP si intéressé par un de nos clubs 🤝)."""
                
                # Utiliser un embed pour une meilleure présentation
                embed = discord.Embed(
                    title="🌸 Présentation - Réseau Prairie 🌸",
                    description=presentation_text,
                    color=0x90EE90
                )
                
                # Footer avec dernière mise à jour
                embed.set_footer(text="💡 Trophées mis à jour automatiquement toutes les heures")
                
                await interaction.followup.send(embed=embed)
                
            except Exception as e:
                logger.error(f"Erreur dans presentation: {e}")
                await interaction.followup.send("Une erreur s'est produite lors de la génération de la présentation.")
        
        @self.bot.tree.command(name="set_rusheur_channel", description="Définit le canal pour l'envoi automatique des meilleurs rusheurs")
        async def set_rusheur_channel(interaction: discord.Interaction):
            await interaction.response.defer()
            
            try:
                self.rusheur_channel_id = interaction.channel.id
                
                embed = discord.Embed(
                    title="✅ Canal configuré",
                    description=f"Les meilleurs rusheurs seront maintenant envoyés automatiquement dans ce canal toutes les demi-heures.",
                    color=0x00ff00
                )
                embed.set_footer(text="💡 Pour arrêter l'envoi automatique, utilisez /stop_rusheur_auto")
                
                await interaction.followup.send(embed=embed)
                logger.info(f"Canal des rusheurs configuré: {interaction.channel.name} (ID: {interaction.channel.id})")
                
            except Exception as e:
                logger.error(f"Erreur dans set_rusheur_channel: {e}")
                await interaction.followup.send("Une erreur s'est produite lors de la configuration du canal.")
        
        @self.bot.tree.command(name="stop_rusheur_auto", description="Arrête l'envoi automatique des meilleurs rusheurs")
        async def stop_rusheur_auto(interaction: discord.Interaction):
            # Vérification du rôle Modo
            if not self.has_modo_role(interaction):
                embed = discord.Embed(
                    title="🚫 Accès refusé",
                    description="Cette commande est réservée aux membres ayant le rôle **Modo 🪻**.",
                    color=0xff0000
                )
                await interaction.response.send_message(embed=embed, ephemeral=True)
                return
                
            await interaction.response.defer()
            
            try:
                self.rusheur_channel_id = None
                self.last_rusheur_message = None
                
                embed = discord.Embed(
                    title="🛑 Envoi automatique arrêté",
                    description="L'envoi automatique des meilleurs rusheurs a été désactivé.",
                    color=0xff9900
                )
                
                await interaction.followup.send(embed=embed)
                logger.info("Envoi automatique des rusheurs arrêté")
                
            except Exception as e:
                logger.error(f"Erreur dans stop_rusheur_auto: {e}")
                await interaction.followup.send("Une erreur s'est produite lors de l'arrêt de l'envoi automatique.")
        
        @self.bot.tree.command(name="test_rusheur_auto", description="Test manuel de l'envoi automatique des rusheurs")
        async def test_rusheur_auto(interaction: discord.Interaction):
            # Vérification du rôle Modo
            if not self.has_modo_role(interaction):
                embed = discord.Embed(
                    title="🚫 Accès refusé",
                    description="Cette commande est réservée aux membres ayant le rôle **Modo 🪻**.",
                    color=0xff0000
                )
                await interaction.response.send_message(embed=embed, ephemeral=True)
                return
                
            await interaction.response.defer()
            
            try:
                # Configurer le canal actuel comme canal de rusheur temporairement pour le test
                old_channel = self.rusheur_channel_id
                self.rusheur_channel_id = interaction.channel.id
                
                # Exécuter manuellement la fonction
                await self.auto_rusheur_update()
                
                # Restaurer l'ancien canal
                self.rusheur_channel_id = old_channel
                
                await interaction.followup.send("✅ Test de l'envoi automatique des rusheurs terminé !")
                
            except Exception as e:
                logger.error(f"Erreur dans test_rusheur_auto: {e}")
                await interaction.followup.send(f"❌ Erreur lors du test: {str(e)}")
        
        @self.bot.tree.command(name="rusheur_status", description="Affiche le statut du système automatique des rusheurs")
        async def rusheur_status(interaction: discord.Interaction):
            # Vérification du rôle Modo
            if not self.has_modo_role(interaction):
                embed = discord.Embed(
                    title="🚫 Accès refusé",
                    description="Cette commande est réservée aux membres ayant le rôle **Modo 🪻**.",
                    color=0xff0000
                )
                await interaction.response.send_message(embed=embed, ephemeral=True)
                return
                
            await interaction.response.defer()
            
            try:
                embed = discord.Embed(
                    title="📊 Statut du système automatique des rusheurs",
                    color=0x3498db
                )
                
                # Statut du canal
                if self.rusheur_channel_id:
                    channel = self.bot.get_channel(self.rusheur_channel_id)
                    if channel:
                        embed.add_field(
                            name="📺 Canal configuré",
                            value=f"✅ {channel.mention} (ID: {self.rusheur_channel_id})",
                            inline=False
                        )
                    else:
                        embed.add_field(
                            name="📺 Canal configuré",
                            value=f"❌ Canal non trouvé (ID: {self.rusheur_channel_id})",
                            inline=False
                        )
                else:
                    embed.add_field(
                        name="📺 Canal configuré",
                        value="❌ Aucun canal configuré",
                        inline=False
                    )
                
                # Statut de la tâche automatique
                if self.auto_rusheur_update.is_running():
                    embed.add_field(
                        name="🔄 Tâche automatique",
                        value="✅ Active (toutes les 30 minutes)",
                        inline=True
                    )
                    
                    # Prochaine exécution
                    if hasattr(self.auto_rusheur_update, 'next_iteration'):
                        next_run = self.auto_rusheur_update.next_iteration
                        if next_run:
                            embed.add_field(
                                name="⏰ Prochaine exécution",
                                value=f"<t:{int(next_run.timestamp())}:R>",
                                inline=True
                            )
                else:
                    embed.add_field(
                        name="🔄 Tâche automatique",
                        value="❌ Inactive",
                        inline=True
                    )
                
                # Statut du dernier message
                if self.last_rusheur_message:
                    embed.add_field(
                        name="💬 Dernier message",
                        value=f"✅ Message ID: {self.last_rusheur_message.id}",
                        inline=True
                    )
                else:
                    embed.add_field(
                        name="💬 Dernier message",
                        value="❌ Aucun message récent",
                        inline=True
                    )
                
                await interaction.followup.send(embed=embed)
                
            except Exception as e:
                logger.error(f"Erreur dans rusheur_status: {e}")
                await interaction.followup.send("Une erreur s'est produite lors de la récupération du statut.")
    
    async def scrape_club_info(self, club_tag):
        """Scrape les informations générales d'un club depuis brawlace.com"""
        try:
            clean_tag = club_tag.replace('#', '').upper()
            url = f'https://brawlace.com/clubs/%23{clean_tag}'
            
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8',
                'Accept-Language': 'en-US,en;q=0.9,fr;q=0.8',
                'Accept-Encoding': 'gzip, deflate, br',
                'DNT': '1',
                'Connection': 'keep-alive',
                'Upgrade-Insecure-Requests': '1',
                'Sec-Fetch-Dest': 'document',
                'Sec-Fetch-Mode': 'navigate',
                'Sec-Fetch-Site': 'none',
                'Cache-Control': 'max-age=0',
                'Referer': 'https://brawlace.com/'
            }
            
            connector = aiohttp.TCPConnector(
                limit=100,
                limit_per_host=30,
                ttl_dns_cache=300,
                use_dns_cache=True,
            )
            
            timeout = aiohttp.ClientTimeout(total=30, connect=10)
            
            async with aiohttp.ClientSession(
                headers=headers, 
                connector=connector,
                timeout=timeout
            ) as session:
                
                await asyncio.sleep(2)
                
                logger.info(f"Scraping info club pour {url}")
                
                async with session.get(url, ssl=False, allow_redirects=True) as response:
                    if response.status == 200:
                        html = await response.text()
                        logger.info(f"HTML club récupéré pour {club_tag}")
                    else:
                        logger.error(f"Erreur HTTP {response.status} pour club {url}")
                        return None
            
            # Parser les informations du club
            club_info = {
                'tag': club_tag,
                'name': '',
                'total_trophies': 0,
                'member_count': 0
            }
            
            # Extraire le nom du club
            name_patterns = [
                r'<h1[^>]*>([^<]+)</h1>',
                r'<title>([^<]*?)\s*-\s*Brawl Ace</title>',
                r'class="club-name[^"]*">([^<]+)<',
            ]
            
            for pattern in name_patterns:
                match = re.search(pattern, html, re.IGNORECASE)
                if match:
                    club_info['name'] = match.group(1).strip()
                    break
            
            # Extraire les trophées totaux - chercher dans les divs/spans de statistiques
            trophy_patterns = [
                r'(?:total|club)\s*trophies?[^>]*>[\s\S]*?([0-9,]+)',
                r'trophies?[^>]*>[\s\S]*?([0-9,]+)',
                r'<span[^>]*trophies?[^>]*>([0-9,]+)',
                r'<div[^>]*>[\s\S]*?([0-9,]{4,})',  # Chercher des nombres avec au moins 4 chiffres
            ]
            
            for pattern in trophy_patterns:
                matches = re.findall(pattern, html, re.IGNORECASE)
                for match in matches:
                    try:
                        trophies = int(match.replace(',', ''))
                        if trophies > 1000:  # Les clubs ont généralement plus de 1000 trophées
                            club_info['total_trophies'] = trophies
                            break
                    except ValueError:
                        continue
                if club_info['total_trophies'] > 0:
                    break
            
            # Extraire le nombre de membres - compter les lignes de joueurs
            member_patterns = [
                r'([0-9]+)\s*/\s*30\s*members?',
                r'members?\s*[:\s]*([0-9]+)',
            ]
            
            for pattern in member_patterns:
                match = re.search(pattern, html, re.IGNORECASE)
                if match:
                    try:
                        club_info['member_count'] = int(match.group(1))
                        break
                    except ValueError:
                        continue
            
            # Si pas trouvé, compter les lignes de tableau (méthode de fallback)
            if club_info['member_count'] == 0:
                tr_matches = re.findall(r'<tr[^>]*>(.*?)</tr>', html, re.DOTALL | re.IGNORECASE)
                member_count = 0
                
                for tr_content in tr_matches:
                    td_matches = re.findall(r'<td[^>]*>(.*?)</td>', tr_content, re.DOTALL | re.IGNORECASE)
                    if len(td_matches) >= 4:
                        # Vérifier si cette ligne contient un joueur
                        player_cell = td_matches[1] if len(td_matches) > 1 else ""
                        if 'data-bs-player-tag' in player_cell or '<a' in player_cell:
                            member_count += 1
                
                club_info['member_count'] = member_count
            
            logger.info(f"Club info scrapé: {club_info['name']} ({club_info['tag']}) - {club_info['total_trophies']:,} trophées, {club_info['member_count']} membres")
            return club_info
            
        except Exception as e:
            logger.error(f"Erreur lors du scraping des infos club {club_tag}: {e}")
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")
            return None
    
    async def scrape_club_data(self, club_tag):
        """Scrape les données d'un club depuis brawlace.com"""
        try:
            clean_tag = club_tag.replace('#', '').upper()
            url = f'https://brawlace.com/clubs/%23{clean_tag}'
            
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8',
                'Accept-Language': 'en-US,en;q=0.9,fr;q=0.8',
                'Accept-Encoding': 'gzip, deflate, br',
                'DNT': '1',
                'Connection': 'keep-alive',
                'Upgrade-Insecure-Requests': '1',
                'Sec-Fetch-Dest': 'document',
                'Sec-Fetch-Mode': 'navigate',
                'Sec-Fetch-Site': 'none',
                'Cache-Control': 'max-age=0',
                'Referer': 'https://brawlace.com/'
            }
            
            # Configuration du connecteur avec timeout plus long
            connector = aiohttp.TCPConnector(
                limit=100,
                limit_per_host=30,
                ttl_dns_cache=300,
                use_dns_cache=True,
            )
            
            # Timeout configuration
            timeout = aiohttp.ClientTimeout(total=30, connect=10)
            
            async with aiohttp.ClientSession(
                headers=headers, 
                connector=connector,
                timeout=timeout
            ) as session:
                
                # Attendre un peu pour éviter d'être détecté comme bot
                await asyncio.sleep(2)
                
                logger.info(f"Tentative de scraping pour {url}")
                
                async with session.get(url, ssl=False, allow_redirects=True) as response:
                    logger.info(f"Status code: {response.status} pour {url}")
                    logger.info(f"Content encoding: {response.headers.get('content-encoding', 'none')}")
                    
                    if response.status == 200:
                        # Le décodage brotli devrait maintenant fonctionner
                        html = await response.text()
                        logger.info(f"HTML récupéré avec succès pour {club_tag}, taille: {len(html)}")
                    else:
                        logger.error(f"Erreur HTTP {response.status} pour {url}")
                        return []
            
            logger.info(f"HTML récupéré pour {club_tag}, taille: {len(html)}")
            
            # Debug: sauvegarder un échantillon du HTML
            if len(html) < 1000:
                logger.warning(f"HTML très court pour {club_tag}: {html[:500]}")
            
            # Parser le HTML plus robustement
            players = []
            
            # Rechercher toutes les lignes de tableau
            tr_matches = re.findall(r'<tr[^>]*>(.*?)</tr>', html, re.DOTALL | re.IGNORECASE)
            logger.info(f"Trouvé {len(tr_matches)} lignes de tableau")
            
            for tr_content in tr_matches:
                # Extraire toutes les cellules td
                td_matches = re.findall(r'<td[^>]*>(.*?)</td>', tr_content, re.DOTALL | re.IGNORECASE)
                
                if len(td_matches) >= 4:
                    # Cellule 1 (index 1) contient généralement le pseudo et l'ID
                    player_cell = td_matches[1] if len(td_matches) > 1 else ""
                    
                    # Extraire le pseudo - chercher dans les balises <font> ou <a>
                    pseudo = ""
                    pseudo_patterns = [
                        r'<font[^>]*>([^<]+)</font>',
                        r'<a[^>]*>([^<]+)</a>',
                        r'>([^<]+)<'
                    ]
                    
                    for pattern in pseudo_patterns:
                        match = re.search(pattern, player_cell)
                        if match and match.group(1).strip():
                            pseudo = match.group(1).strip()
                            break
                    
                    # Extraire l'ID du joueur
                    player_id = ""
                    id_patterns = [
                        r'data-bs-player-tag=[\'"]([^\'""]*)[\'"]',
                        r'player-tag=[\'"]([^\'""]*)[\'"]',
                        r'href="[^"]*player/([^/"]*)"'
                    ]
                    
                    for pattern in id_patterns:
                        match = re.search(pattern, player_cell)
                        if match:
                            player_id = match.group(1).strip()
                            if not player_id.startswith('#'):
                                player_id = '#' + player_id
                            break
                    
                    # Cellule des trophées (généralement index 3)
                    trophy_cell = td_matches[3] if len(td_matches) > 3 else ""
                    
                    # Extraire les trophées
                    trophies = 0
                    trophy_patterns = [
                        r'<font[^>]*>([0-9,]+)</font>',
                        r'>([0-9,]+)<',
                        r'([0-9,]+)'
                    ]
                    
                    for pattern in trophy_patterns:
                        match = re.search(pattern, trophy_cell)
                        if match:
                            trophies_str = match.group(1).strip().replace(',', '').replace(' ', '')
                            try:
                                trophies = int(trophies_str)
                                break
                            except ValueError:
                                continue
                    
                    # Validation et ajout du joueur
                    if pseudo and player_id and trophies > 0:
                        players.append({
                            'pseudo': pseudo,
                            'id': player_id,
                            'trophies': trophies
                        })
                        logger.debug(f"Joueur trouvé: {pseudo} ({player_id}) - {trophies} trophées")
                    else:
                        # Debug des cas où on ne trouve pas de données
                        if not pseudo:
                            logger.debug(f"Pseudo manquant dans: {player_cell[:100]}")
                        if not player_id:
                            logger.debug(f"ID manquant dans: {player_cell[:100]}")
                        if trophies <= 0:
                            logger.debug(f"Trophées invalides dans: {trophy_cell[:100]}")
            
            logger.info(f"Scrapé {len(players)} joueurs pour le club {club_tag}")
            
            # Si aucun joueur trouvé, log un échantillon du HTML pour debug
            if len(players) == 0 and len(html) > 0:
                logger.warning(f"Aucun joueur trouvé. Échantillon HTML: {html[:1000]}")
            
            return players
            
        except Exception as e:
            logger.error(f"Erreur lors du scraping de {club_tag}: {e}")
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")
            return []
    
    async def update_club_info_in_firebase(self, club_info, club_name):
        """Met à jour les informations du club dans Firebase"""
        try:
            if not club_info:
                logger.warning(f"Pas d'informations club à mettre à jour pour {club_name}")
                return
            
            current_time = datetime.now(timezone.utc)
            
            club_data = {
                'name': club_name,
                'tag': club_info['tag'],
                'scraped_name': club_info['name'],  # Nom scrapé du site
                'total_trophies': club_info['total_trophies'],
                'member_count': club_info['member_count'],
                'updatedAt': current_time
            }
            
            # Utiliser le tag comme ID du document
            club_ref = self.db.collection('clubs').document(club_info['tag'])
            
            # Vérifier si le club existe déjà 
            club_doc = club_ref.get()
            if club_doc.exists:
                club_ref.update(club_data)
                logger.info(f"Club {club_name} mis à jour dans Firebase")
            else:
                club_ref.set(club_data)
                logger.info(f"Club {club_name} créé dans Firebase")
                
        except Exception as e:
            logger.error(f"Erreur lors de la mise à jour des infos club {club_name}: {e}")
    
    async def scrape_and_update_club(self, club_tag, club_name):
        """Scrape et met à jour les données d'un club dans Firebase (joueurs + infos club)"""
        # Scraper les joueurs
        players_data = await self.scrape_club_data(club_tag)
        updated_players = 0
        
        for player_data in players_data:
            try:
                player_ref = self.db.collection('players').document(player_data['id'])
                player_doc = player_ref.get()
                
                current_time = datetime.now(timezone.utc)
                
                if player_doc.exists:
                    # Mettre à jour le joueur existant - NE PAS TOUCHER trophees_debut_mois
                    update_data = {
                        'pseudo': player_data['pseudo'],
                        'trophees_actuels': player_data['trophies'],
                        'club': club_name,
                        'updatedAt': current_time
                    }
                    player_ref.update(update_data)
                    logger.debug(f"Joueur existant mis à jour: {player_data['pseudo']} - trophees_debut_mois préservé")
                else:
                    # Créer un nouveau joueur - ici on initialise trophees_debut_mois = trophees_actuels
                    new_player_data = {
                        'pseudo': player_data['pseudo'],
                        'id': player_data['id'],
                        'trophees_debut_mois': player_data['trophies'],  # Seulement pour les nouveaux joueurs
                        'trophees_actuels': player_data['trophies'],
                        'club': club_name,
                        'updatedAt': current_time
                    }
                    player_ref.set(new_player_data)
                    logger.debug(f"Nouveau joueur créé: {player_data['pseudo']} - trophees_debut_mois initialisé")
                
                updated_players += 1
                
            except Exception as e:
                logger.error(f"Erreur lors de la mise à jour du joueur {player_data['id']}: {e}")
        
        # Scraper et mettre à jour les infos du club
        club_info = await self.scrape_club_info(club_tag)
        await self.update_club_info_in_firebase(club_info, club_name)
        
        logger.info(f"Mis à jour {updated_players} joueurs et infos pour le club {club_name}")
        return updated_players
    
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
    
    @tasks.loop(hours=1)  # Changé à 1 heure
    async def auto_update(self):
        """Met à jour automatiquement tous les clubs toutes les heures"""
        logger.info("Début de la mise à jour automatique (toutes les heures)")
        
        for club_name, club_tag in self.clubs.items():
            try:
                await self.scrape_and_update_club(club_tag, club_name)
                await asyncio.sleep(5)  # Pause de 5 secondes entre chaque club
            except Exception as e:
                logger.error(f"Erreur lors de la mise à jour automatique de {club_name}: {e}")
        
        logger.info("Mise à jour automatique terminée")
    
    @tasks.loop(minutes=30)  # Toutes les 30 minutes
    async def auto_rusheur_update(self):
        """Envoie automatiquement les meilleurs rusheurs toutes les demi-heures"""
        if not self.rusheur_channel_id:
            logger.info("Pas de canal rusheur configuré, skip")
            return  # Pas de canal configuré
        
        try:
            channel = self.bot.get_channel(self.rusheur_channel_id)
            if not channel:
                logger.error(f"Canal rusheur non trouvé: {self.rusheur_channel_id}")
                self.rusheur_channel_id = None  # Reset si le canal n'existe plus
                return
            
            logger.info(f"Début de l'envoi automatique des meilleurs rusheurs dans {channel.name}")
            
            # Supprimer le message précédent s'il existe
            if self.last_rusheur_message:
                try:
                    await self.last_rusheur_message.delete()
                    logger.info("Ancien message des rusheurs supprimé")
                except discord.NotFound:
                    logger.info("Ancien message des rusheurs déjà supprimé")
                except discord.Forbidden:
                    logger.error("Permissions insuffisantes pour supprimer l'ancien message")
                except Exception as e:
                    logger.error(f"Erreur lors de la suppression de l'ancien message: {e}")
                finally:
                    self.last_rusheur_message = None
            
            # Créer l'embed des meilleurs rusheurs
            embed = discord.Embed(
                title="🚀 Meilleurs rusheurs du mois",
                description="Mise à jour automatique toutes les 30 minutes",
                color=0xffd700
            )
            
            rusheurs_found = False
            total_rusheurs = 0
            
            for club_name in self.clubs.keys():
                try:
                    best_player = await self.get_best_rusher(club_name)
                    if best_player:
                        diff = best_player['trophees_actuels'] - best_player['trophees_debut_mois']
                        if diff >= 0:  # Ne afficher que les gains positifs ou nuls
                            embed.add_field(
                                name=f"🏆 {club_name}",
                                value=f"**{best_player['pseudo']}**\n+{diff:,} trophées",
                                inline=True
                            )
                            rusheurs_found = True
                            total_rusheurs += 1
                            logger.info(f"Rusheur trouvé pour {club_name}: {best_player['pseudo']} (+{diff})")
                        else:
                            embed.add_field(
                                name=f"📉 {club_name}",
                                value=f"**{best_player['pseudo']}**\n{diff:,} trophées",
                                inline=True
                            )
                            total_rusheurs += 1
                    else:
                        embed.add_field(
                            name=f"❌ {club_name}",
                            value="Aucun joueur trouvé",
                            inline=True
                        )
                        logger.warning(f"Aucun rusheur trouvé pour {club_name}")
                except Exception as e:
                    logger.error(f"Erreur lors de la récupération du rusheur pour {club_name}: {e}")
                    embed.add_field(
                        name=f"⚠️ {club_name}",
                        value="Erreur de récupération",
                        inline=True
                    )
            
            # Ajouter un footer avec l'heure de mise à jour
            from datetime import datetime, timezone
            now = datetime.now(timezone.utc)
            embed.set_footer(text=f"🕐 Mis à jour automatiquement le {now.strftime('%d/%m/%Y à %H:%M')} UTC • {total_rusheurs} club(s) traité(s)")
            
            # Envoyer le nouveau message
            try:
                self.last_rusheur_message = await channel.send(embed=embed)
                logger.info(f"Message des meilleurs rusheurs envoyé avec succès dans {channel.name} (ID: {self.last_rusheur_message.id})")
            except discord.Forbidden:
                logger.error(f"Permissions insuffisantes pour envoyer un message dans {channel.name}")
                self.rusheur_channel_id = None  # Reset le canal si pas de permissions
            except discord.HTTPException as e:
                logger.error(f"Erreur HTTP lors de l'envoi du message: {e}")
            except Exception as e:
                logger.error(f"Erreur inattendue lors de l'envoi du message: {e}")
                
        except Exception as e:
            logger.error(f"Erreur générale lors de l'envoi automatique des rusheurs: {e}")
            import traceback
            logger.error(f"Traceback complet: {traceback.format_exc()}")
    
    @auto_rusheur_update.before_loop
    async def before_auto_rusheur_update(self):
        """Attend que le bot soit prêt avant de démarrer l'envoi automatique"""
        await self.bot.wait_until_ready()
        logger.info("Bot prêt, l'envoi automatique des rusheurs peut démarrer dans 30 minutes")
        # Optionnel: attendre encore un peu pour être sûr que tout est initialisé
        await asyncio.sleep(10)
    
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
