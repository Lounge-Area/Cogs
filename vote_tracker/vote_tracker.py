import random
import asyncio
from datetime import datetime, timedelta
from typing import Optional
from redbot.core import commands, Config, checks
from redbot.core.utils.predicates import MessagePredicate
from redbot.core.utils.chat_formatting import box, humanize_timedelta

class VoteTracker(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=8675309)
        default_guild = {
            "channel": None,
            "role": None,
            "points_per_vote": 10,
            "active_giveaways": {}
        }
        default_member = {
            "points": 0,
            "last_vote": None,
            "total_votes": 0
        }
        self.config.register_guild(**default_guild)
        self.config.register_member(**default_member)
        self.giveaway_tasks = {}

    @commands.group()
    @checks.admin_or_permissions(administrator=True)
    async def voteconfig(self, ctx):
        """Configure the vote tracking system"""
        pass

    @voteconfig.command()
    async def channel(self, ctx, channel: discord.TextChannel):
        """Set the announcement channel"""
        await self.config.guild(ctx.guild).channel.set(channel.id)
        await ctx.send(f"Announcement channel set to {channel.mention}")

    @voteconfig.command()
    async def role(self, ctx, role: discord.Role):
        """Set the voter role"""
        await self.config.guild(ctx.guild).role.set(role.id)
        await ctx.send(f"Voter role set to {role.mention}")

    @voteconfig.command()
    async def points(self, ctx, amount: int):
        """Set points per vote"""
        await self.config.guild(ctx.guild).points_per_vote.set(amount)
        await ctx.send(f"Points per vote set to {amount}")

    @commands.group()
    @checks.admin_or_permissions(administrator=True)
    async def giveaway(self, ctx):
        """Manage giveaways"""
        pass

    @giveaway.command(name="start")
    async def giveaway_start(self, ctx, duration: str, *, prize: str):
        """Start a giveaway
        
        Duration format: 1d2h3m (days, hours, minutes)
        Use --weighted flag for vote-weighted entries
        """
        weighted = "--weighted" in prize
        prize = prize.replace("--weighted", "").strip()
        
        # Parse duration
        total_seconds = 0
        time_dict = {"d": 86400, "h": 3600, "m": 60}
        for char in time_dict:
            if char in duration:
                num = duration.split(char)[0]
                if num.isdigit():
                    total_seconds += int(num) * time_dict[char]
                duration = duration.split(char)[1]

        if total_seconds == 0:
            await ctx.send("Invalid duration format. Use 1d2h3m format.")
            return

        end_time = datetime.utcnow() + timedelta(seconds=total_seconds)
        
        # Create giveaway message
        channel_id = await self.config.guild(ctx.guild).channel()
        channel = ctx.guild.get_channel(channel_id)
        
        embed = discord.Embed(
            title="🎉 GIVEAWAY 🎉",
            description=f"**Prize:** {prize}\n\n"
                       f"React with 🎉 to enter!\n\n"
                       f"{'Vote-weighted entries are enabled!' if weighted else 'Everyone has equal chances!'}\n"
                       f"Ends: {end_time.strftime('%Y-%m-%d %H:%M UTC')}",
            color=discord.Color.purple()
        )
        
        msg = await channel.send(embed=embed)
        await msg.add_reaction("🎉")
        
        # Store giveaway data
        giveaway_data = {
            "prize": prize,
            "end_time": end_time.timestamp(),
            "message_id": msg.id,
            "channel_id": channel.id,
            "weighted": weighted
        }
        
        async with self.config.guild(ctx.guild).active_giveaways() as giveaways:
            giveaways[str(msg.id)] = giveaway_data
        
        # Schedule end task
        self.giveaway_tasks[msg.id] = asyncio.create_task(
            self.end_giveaway(ctx.guild, msg.id, total_seconds)
        )

    async def end_giveaway(self, guild, message_id, delay):
        """End a giveaway after the specified delay"""
        await asyncio.sleep(delay)
        
        async with self.config.guild(guild).active_giveaways() as giveaways:
            if str(message_id) not in giveaways:
                return
            
            giveaway_data = giveaways.pop(str(message_id))
        
        channel = guild.get_channel(giveaway_data["channel_id"])
        if not channel:
            return
        
        try:
            message = await channel.fetch_message(message_id)
            reaction = next(
                (r for r in message.reactions if str(r.emoji) == "🎉"), None
            )
            
            if not reaction or reaction.count <= 1:
                await channel.send("No valid entries for the giveaway!")
                return
            
            users = [user async for user in reaction.users() if not user.bot]
            
            if giveaway_data["weighted"]:
                weighted_users = []
                for user in users:
                    user_data = await self.config.member(user).all()
                    points = user_data["points"]
                    weighted_users.extend([user] * (points + 1))  # +1 for base entry
                
                winner = random.choice(weighted_users)
            else:
                winner = random.choice(users)
            
            await channel.send(
                f"🎉 Congratulations {winner.mention}! "
                f"You won: **{giveaway_data['prize']}**!"
            )
            
        except discord.NotFound:
            pass
        
        if message_id in self.giveaway_tasks:
            del self.giveaway_tasks[message_id]

    @commands.command()
    async def votes(self, ctx, member: Optional[discord.Member] = None):
        """Check vote statistics"""
        target = member or ctx.author
        data = await self.config.member(target).all()
        
        embed = discord.Embed(
            title=f"Vote Statistics for {target.display_name}",
            color=discord.Color.purple()
        )
        embed.add_field(name="Total Votes", value=data["total_votes"])
        embed.add_field(name="Current Points", value=data["points"])
        
        if data["last_vote"]:
            last_vote = datetime.fromtimestamp(data["last_vote"])
            embed.add_field(
                name="Last Vote",
                value=last_vote.strftime("%Y-%m-%d %H:%M UTC")
            )
        
        await ctx.send(embed=embed)