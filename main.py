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
        logger.info("=== INITIALISATION DU BOT ===")
        
        # Vérifier les variables d'environnement
        discord_token = os.environ.get('DISCORD_TOKEN')
        if discord_token:
            logger.info("✅ DISCORD_TOKEN trouvé")
        else:
            logger.error("❌ DISCORD_TOKEN manquant")
        
        port = os.environ.get('PORT', '5000')
        logger.info(f"✅ PORT configuré sur: {port}")
        
        try:
            # Initialisation Discord
            logger.info("Initialisation Discord...")
            intents = discord.Intents.default()
            intents.message_content = True
            self.bot = commands.Bot(command_prefix='!', intents=intents)
            logger.info("✅ Bot Discord initialisé")
            
            # Initialisation Firebase
            logger.info("Initialisation Firebase...")
            self.init_firebase()
            logger.info("✅ Firebase initialisé")
            
            # Configuration des clubs
            logger.info("Configuration des clubs...")
            self.clubs = {
                "Prairie Fleurie": "#2C9Y28JPP",
                "Prairie Céleste": "#2JUVYQ0YV",
                "Prairie Gelée": "#2CJJLLUQ9",
                "Prairie étoilée": "#29UPLG8QQ",
                "Prairie Brulée": "#2YGPRQYCC",
                "Mini Prairie": "#JY89VGGP",
            }
            logger.info(f"✅ {len(self.clubs)} clubs configurés")
            
            # Flask pour le ping d'Uptime Robot
            logger.info("Initialisation Flask...")
            self.app = Flask(__name__)
            logger.info("✅ Flask initialisé")
            
            # Variables pour les rusheurs
            self.last_rusheur_message = None
            self.rusheur_channel_id = None
            
            # ID du rôle Modo
            self.MODO_ROLE_ID = 1185678999335219311
            
            logger.info("Configuration des événements Discord...")
            self.setup_discord_events()
            logger.info("✅ Événements Discord configurés")
            
            logger.info("Configuration des routes Flask...")
            self.setup_flask_routes()
            logger.info("✅ Routes Flask configurées")
            
            logger.info("=== INITIALISATION TERMINÉE ===")
            
        except Exception as e:
            logger.error(f"❌ ERREUR LORS DE L'INITIALISATION: {e}")
            raise
    
    def has_modo_role(self, interaction: discord.Interaction) -> bool:
        """Vérifie si l'utilisateur a le rôle Modo"""
        try:
            # Log pour debug
            logger.info(f"Vérification des permissions pour l'utilisateur {interaction.user.name} (ID: {interaction.user.id})")
            
            if not interaction.guild:
                logger.warning("Pas de guild trouvé dans l'interaction")
                return False
            
            # Essayer d'abord avec interaction.user si c'est déjà un Member
            member = None
            if hasattr(interaction.user, 'roles'):
                member = interaction.user
                logger.info("Utilisation directe de interaction.user (déjà un Member)")
            else:
                # Sinon, récupérer le membre depuis le guild
                member = interaction.guild.get_member(interaction.user.id)
                logger.info("Récupération du membre depuis le guild")
            
            if not member:
                logger.warning(f"Membre non trouvé pour l'ID {interaction.user.id}")
                return False
            
            # Log des rôles de l'utilisateur
            user_roles = [f"{role.name} (ID: {role.id})" for role in member.roles]
            logger.info(f"Rôles de l'utilisateur: {user_roles}")
            logger.info(f"ID du rôle Modo recherché: {self.MODO_ROLE_ID}")
            
            # Vérifier si l'utilisateur a le rôle Modo (comparaison flexible)
            for role in member.roles:
                if role.id == self.MODO_ROLE_ID or str(role.id) == str(self.MODO_ROLE_ID):
                    logger.info(f"Rôle Modo trouvé: {role.name} (ID: {role.id})")
                    return True
            
            logger.warning("Rôle Modo non trouvé pour cet utilisateur")
            return False
            
        except Exception as e:
            logger.error(f"Erreur lors de la vérification du rôle Modo: {e}")
            return False
        
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
    
    def run_flask(self):
        """Lance le serveur Flask dans un thread séparé"""
        self.app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))
    
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
            if not self.auto_update.is_running():
                self.auto_update.start()
                logger.info("Mise à jour automatique programmée toutes les heures")
            
            # Démarrer l'envoi automatique des meilleurs rusheurs
            if not self.auto_rusheur_update.is_running():
                self.auto_rusheur_update.start()
                logger.info("Envoi automatique des meilleurs rusheurs programmé toutes les demi-heures")
        
        @self.bot.event
        async def on_error(event, *args, **kwargs):
            logger.error(f"Erreur Discord dans {event}: {args}, {kwargs}")

        @self.bot.event  
        async def on_command_error(ctx, error):
            logger.error(f"Erreur de commande: {error}")
        
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
                await interaction.response.send_message("❌ Vous n'avez pas les permissions nécessaires pour utiliser cette commande.", ephemeral=True)
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
            # Vérification du rôle Modo
            if not self.has_modo_role(interaction):
                await interaction.response.send_message("❌ Vous n'avez pas les permissions nécessaires pour utiliser cette commande.", ephemeral=True)
                return
                
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
            # Vérification du rôle Modo
            if not self.has_modo_role(interaction):
                await interaction.response.send_message("❌ Vous n'avez pas les permissions nécessaires pour utiliser cette commande.", ephemeral=True)
                return
                
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
        
        @self.bot.tree.command(name="debug_roles", description="Affiche tous les rôles du serveur (pour debug)")
        async def debug_roles(interaction: discord.Interaction):
            await interaction.response.defer()
            
            try:
                if not interaction.guild:
                    await interaction.followup.send("Cette commande ne fonctionne que dans un serveur.")
                    return
                
                roles_list = []
                for role in interaction.guild.roles:
                    roles_list.append(f"**{role.name}** - ID: `{role.id}`")
                
                # Diviser en plusieurs messages si nécessaire
                roles_text = "\n".join(roles_list)
                
                if len(roles_text) > 2000:
                    # Si trop long, envoyer en plusieurs parties
                    chunks = [roles_text[i:i+1900] for i in range(0, len(roles_text), 1900)]
                    for i, chunk in enumerate(chunks):
                        embed = discord.Embed(
                            title=f"🔧 Rôles du serveur (partie {i+1}/{len(chunks)})",
                            description=chunk,
                            color=0x0099ff
                        )
                        await interaction.followup.send(embed=embed)
                else:
                    embed = discord.Embed(
                        title="🔧 Rôles du serveur",
                        description=roles_text,
                        color=0x0099ff
                    )
                    await interaction.followup.send(embed=embed)
                
                # Afficher aussi les rôles de l'utilisateur
                member = interaction.guild.get_member(interaction.user.id)
                if member:
                    user_roles = [f"**{role.name}** - ID: `{role.id}`" for role in member.roles]
                    user_embed = discord.Embed(
                        title="👤 Vos rôles",
                        description="\n".join(user_roles),
                        color=0x00ff00
                    )
                    await interaction.followup.send(embed=user_embed)
                
            except Exception as e:
                logger.error(f"Erreur dans debug_roles: {e}")
                await interaction.followup.send("Une erreur s'est produite lors de l'affichage des rôles.")
        
        @self.bot.tree.command(name="places_libres", description="Affiche le nombre de places libres dans chaque club")
        async def places_libres(interaction: discord.Interaction):
            # Vérification du rôle Modo
            if not self.has_modo_role(interaction):
                await interaction.response.send_message("❌ Vous n'avez pas les permissions nécessaires pour utiliser cette commande.", ephemeral=True)
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
                            emoji = "🟢"  # Complet
                        elif places_libres <= 5:
                            emoji = "🟡"  # Presque plein
                        else:
                            emoji = "🔴"  # Places disponibles
                        
                        embed.add_field(
                            name=f"{emoji} {club_name}",
                            value=f"**{places_libres}** place(s) libre(s)",
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
                    name="📊 Tous les clubs Prairie",
                    value=f"🟢 **{total_places_libres}** places libres au total\n👥 **{total_members}/180** membres",
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
                await interaction.response.send_message("❌ Vous n'avez pas les permissions nécessaires pour utiliser cette commande.", ephemeral=True)
                return
                
            await interaction.response.defer()
            
            try:
                # Mapping des clubs avec leurs emojis et seuils
                clubs_info = {
                    "Prairie Fleurie": {"emoji": "🌸", "seuil": "60k", "tag": "#2C9Y28JPP"},
                    "Prairie Céleste": {"emoji": "🪽", "seuil": "60k", "tag": "#2JUVYQ0YV"},
                    "Prairie Gelée": {"emoji": "❄️", "seuil": "60k", "tag": "#2CJJLLUQ9"},
                    "Prairie étoilée": {"emoji": "⭐", "seuil": "55k", "tag": "#29UPLG8QQ"},
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
            # Vérification du rôle Modo
            if not self.has_modo_role(interaction):
                await interaction.response.send_message("❌ Vous n'avez pas les permissions nécessaires pour utiliser cette commande.", ephemeral=True)
                return
                
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
                await interaction.response.send_message("❌ Vous n'avez pas les permissions nécessaires pour utiliser cette commande.", ephemeral=True)
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
        
        @self.bot.tree.command(name="club_info", description="Affiche les informations détaillées de tous les clubs")
        async def club_info(interaction: discord.Interaction):
            # Vérification du rôle Modo
            if not self.has_modo_role(interaction):
                await interaction.response.send_message("❌ Vous n'avez pas les permissions nécessaires pour utiliser cette commande.", ephemeral=True)
                return
                
            await interaction.response.defer()
            
            try:
                embed = discord.Embed(
                    title="📊 Informations détaillées des clubs",
                    description="Données scrapées en temps réel depuis BrawlAce",
                    color=0x3498db
                )
                
                for club_name, club_tag in self.clubs.items():
                    try:
                        # Scraper les données du club
                        club_info = await self.scrape_club_info_detailed(club_tag)
                        
                        if club_info:
                            # Formatage des trophées
                            total_trophies = club_info['total_trophies']
                            if total_trophies >= 1000000:
                                trophies_display = f"{total_trophies / 1000000:.2f}M"
                            else:
                                trophies_display = f"{total_trophies / 1000:.0f}k"
                            
                            # Places libres
                            places_libres = 30 - club_info['member_count']
                            
                            # Intervalle trophées
                            if club_info['min_trophies'] > 0 and club_info['max_trophies'] > 0:
                                intervalle = f"{club_info['min_trophies']:,} - {club_info['max_trophies']:,}"
                            else:
                                intervalle = "Non disponible"
                            
                            # Emoji selon le nombre de places
                            if places_libres == 0:
                                emoji = "🔴"  # Complet
                            elif places_libres <= 5:
                                emoji = "🟡"  # Presque plein
                            else:
                                emoji = "🟢"  # Places disponibles
                            
                            field_value = f"""**{emoji} {places_libres}** place(s) libre(s)
🏆 **{trophies_display}** trophées totaux
📈 **{intervalle}** (min-max)"""
                            
                            embed.add_field(
                                name=f"🌸 {club_name}",
                                value=field_value,
                                inline=True
                            )
                            
                            logger.info(f"Club info scrapé pour {club_name}: {club_info['member_count']} membres, {total_trophies} trophées")
                        
                        else:
                            embed.add_field(
                                name=f"❌ {club_name}",
                                value="Erreur de récupération\ndes données",
                                inline=True
                            )
                            logger.error(f"Erreur lors du scraping de {club_name}")
                        
                        # Pause entre chaque scraping
                        await asyncio.sleep(2)
                        
                    except Exception as e:
                        logger.error(f"Erreur lors du scraping de {club_name}: {e}")
                        embed.add_field(
                            name=f"⚠️ {club_name}",
                            value="Erreur temporaire",
                            inline=True
                        )
                
                # Footer avec heure de mise à jour
                now = datetime.now(timezone.utc)
                embed.set_footer(text=f"🕑 Données scrapées le {now.strftime('%d/%m/%Y à %H:%M')} UTC")
                
                await interaction.followup.send(embed=embed)
                
            except Exception as e:
                logger.error(f"Erreur dans club_info: {e}")
                await interaction.followup.send("Une erreur s'est produite lors de la récupération des informations des clubs.")
    
    # Tâches automatiques
    @tasks.loop(hours=1)
    async def auto_update(self):
        """Met à jour automatiquement tous les clubs toutes les heures"""
        try:
            logger.info("Début de la mise à jour automatique des clubs")
            for club_name, club_tag in self.clubs.items():
                try:
                    updated_count = await self.scrape_and_update_club(club_tag, club_name)
                    logger.info(f"Mise à jour automatique de {club_name}: {updated_count} joueurs")
                    await asyncio.sleep(30)  # Pause entre chaque club
                except Exception as e:
                    logger.error(f"Erreur lors de la mise à jour automatique de {club_name}: {e}")
            
            logger.info("Mise à jour automatique terminée")
            
        except Exception as e:
            logger.error(f"Erreur générale lors de la mise à jour automatique: {e}")

    @auto_update.before_loop
    async def before_auto_update(self):
        """Attendre que le bot soit prêt avant de commencer les tâches"""
        await self.bot.wait_until_ready()

    @tasks.loop(minutes=30)
    async def auto_rusheur_update(self):
        """Envoie automatiquement les meilleurs rusheurs toutes les demi-heures"""
        try:
            if not self.rusheur_channel_id:
                return
            
            channel = self.bot.get_channel(self.rusheur_channel_id)
            if not channel:
                logger.warning(f"Canal rusheur non trouvé: {self.rusheur_channel_id}")
                return
            
            # Créer l'embed des meilleurs rusheurs
            embed = discord.Embed(
                title="🚀 Meilleurs rusheurs du mois",
                color=0xffd700
            )
            
            for club_name in self.clubs.keys():
                try:
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
                except Exception as e:
                    logger.error(f"Erreur lors de la récupération du meilleur rusheur pour {club_name}: {e}")
            
            # Supprimer le message précédent s'il existe
            if self.last_rusheur_message:
                try:
                    await self.last_rusheur_message.delete()
                except:
                    pass
            
            # Envoyer le nouveau message
            self.last_rusheur_message = await channel.send(embed=embed)
            logger.info("Message des meilleurs rusheurs envoyé automatiquement")
            
        except Exception as e:
            logger.error(f"Erreur lors de l'envoi automatique des rusheurs: {e}")

    @auto_rusheur_update.before_loop
    async def before_auto_rusheur_update(self):
        """Attendre que le bot soit prêt avant de commencer les tâches"""
        await self.bot.wait_until_ready()
    
    # Méthodes utilitaires
    async def scrape_and_update_club(self, club_tag, club_name):
        """Scrape et met à jour les données d'un club"""
        try:
            club_info = await self.scrape_club_info_detailed(club_tag)
            if not club_info:
                logger.error(f"Impossible de scraper les données pour {club_name}")
                return 0
            
            # Mettre à jour les données du club dans Firestore
            club_ref = self.db.collection('clubs').document(club_tag)
            club_ref.set({
                'name': club_name,
                'tag': club_tag,
                'total_trophies': club_info['total_trophies'],
                'member_count': club_info['member_count'],
                'min_trophies': club_info['min_trophies'],
                'max_trophies': club_info['max_trophies'],
                'updatedAt': datetime.now(timezone.utc)
            }, merge=True)
            
            # Ici vous devriez également scraper les joueurs individuels
            # et mettre à jour leurs trophées actuels
            # Cette partie dépend de votre logique de scraping des joueurs
            
            logger.info(f"Club {club_name} mis à jour: {club_info['member_count']} membres")
            return club_info['member_count']
            
        except Exception as e:
            logger.error(f"Erreur lors de la mise à jour de {club_name}: {e}")
            return 0

    async def get_best_rusher(self, club_name):
        """Récupère le meilleur rusheur d'un club"""
        try:
            players_ref = self.db.collection('players')
            query = players_ref.where('club', '==', club_name)
            docs = query.stream()
            
            best_player = None
            best_diff = -1
            
            for doc in docs:
                player_data = doc.to_dict()
                diff = player_data['trophees_actuels'] - player_data['trophees_debut_mois']
                
                if diff > best_diff:
                    best_diff = diff
                    best_player = player_data
            
            return best_player
            
        except Exception as e:
            logger.error(f"Erreur lors de la récupération du meilleur rusheur pour {club_name}: {e}")
            return None
    
    async def scrape_club_info_detailed(self, club_tag):
        """Scrape les informations détaillées d'un club depuis brawlace.com avec min/max trophées"""
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
            
            # Configuration du connecteur avec timeout
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
                
                # Attendre un peu pour éviter d'être détecté comme bot
                await asyncio.sleep(2)
                
                logger.info(f"Scraping détaillé pour {url}")
                
                async with session.get(url, ssl=False, allow_redirects=True) as response:
                    if response.status == 200:
                        html = await response.text()
                        logger.info(f"HTML récupéré pour {club_tag}, taille: {len(html)}")
                    else:
                        logger.error(f"Erreur HTTP {response.status} pour {url}")
                        return None
            
            # Parser les informations du club
            club_info = {
                'tag': club_tag,
                'name': '',
                'total_trophies': 0,
                'member_count': 0,
                'min_trophies': 0,
                'max_trophies': 0
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
            
            # Extraire les trophées totaux
            trophy_patterns = [
                r'(?:total|club)\s*trophies?[^>]*>[\s\S]*?([0-9,]+)',
                r'trophies?[^>]*>[\s\S]*?([0-9,]+)',
                r'<span[^>]*trophies?[^>]*>([0-9,]+)',
                r'<div[^>]*>[\s\S]*?([0-9,]{4,})',
            ]
            
            for pattern in trophy_patterns:
                matches = re.findall(pattern, html, re.IGNORECASE)
                for match in matches:
                    try:
                        trophies = int(match.replace(',', ''))
                        if trophies > 1000:
                            club_info['total_trophies'] = trophies
                            break
                    except ValueError:
                        continue
                if club_info['total_trophies'] > 0:
                    break
            
            # Extraire les trophées des joueurs pour calculer min/max
            player_trophies = []
            
            # Rechercher toutes les lignes de tableau
            tr_matches = re.findall(r'<tr[^>]*>(.*?)</tr>', html, re.DOTALL | re.IGNORECASE)
            
            for tr_content in tr_matches:
                td_matches = re.findall(r'<td[^>]*>(.*?)</td>', tr_content, re.DOTALL | re.IGNORECASE)
                
                if len(td_matches) >= 4:
                    # Cellule 1 pour vérifier si c'est bien un joueur
                    player_cell = td_matches[1] if len(td_matches) > 1 else ""
                    
                    # Vérifier si cette ligne contient un joueur
                    if 'data-bs-player-tag' in player_cell or '<a' in player_cell:
                        # Cellule des trophées (généralement index 3)
                        trophy_cell = td_matches[3] if len(td_matches) > 3 else ""
                        
                        # Extraire les trophées
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
                                    if trophies > 0:
                                        player_trophies.append(trophies)
                                        break
                                except ValueError:
                                    continue
            
            # Calculer min/max et nombre de membres
            if player_trophies:
                club_info['min_trophies'] = min(player_trophies)
                club_info['max_trophies'] = max(player_trophies)
                club_info['member_count'] = len(player_trophies)
            else:
                # Fallback: essayer de récupérer le nombre de membres d'une autre façon
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
            
            logger.info(f"Club info détaillé scrapé: {club_info['name']} ({club_info['tag']}) - {club_info['total_trophies']:,} trophées, {club_info['member_count']} membres, trophées: {club_info['min_trophies']}-{club_info['max_trophies']}")
            return club_info
            
        except Exception as e:
            logger.error(f"Erreur lors du scraping détaillé de {club_tag}: {e}")
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")
            return None
    
    def start(self):
        """Démarre le bot Discord et le serveur Flask"""
        try:
            # Démarrer Flask dans un thread séparé
            flask_thread = threading.Thread(target=self.run_flask)
            flask_thread.daemon = True
            flask_thread.start()
            
            logger.info("Serveur Flask démarré")
            
            # Démarrer le bot Discord
            token = os.environ.get('DISCORD_TOKEN')
            if not token:
                logger.error("DISCORD_TOKEN non trouvé dans les variables d'environnement")
                raise ValueError("DISCORD_TOKEN non trouvé")
            
            logger.info("Démarrage du bot Discord...")
            self.bot.run(token, log_handler=None)  # Désactive le handler par défaut
            
        except KeyboardInterrupt:
            logger.info("Arrêt du bot par l'utilisateur")
        except Exception as e:
            logger.error(f"Erreur fatale lors du démarrage: {e}")
            raise

# Point d'entrée principal
if __name__ == "__main__":
    bot = BrawlStarsBot()
    bot.start()
