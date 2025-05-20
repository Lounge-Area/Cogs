from redbot.core import commands, Config
import discord
import aiohttp
import asyncio

class VoteTracker(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=1363900412893204660)
        default_guild = {
            "vote_channel": None,
            "vote_role": None,
            "points_per_vote": 10
        }
        default_member = {
            "vote_points": 0,
            "total_votes": 0
        }
        self.config.register_guild(**default_guild)
        self.config.register_member(**default_member)

    @commands.group()
    @commands.admin()
    async def voteconfig(self, ctx):
        """Configure the vote tracking system"""
        pass

    @voteconfig.command()
    async def channel(self, ctx, channel: discord.TextChannel):
        """Set the channel for vote announcements"""
        await self.config.guild(ctx.guild).vote_channel.set(channel.id)
        await ctx.send(f"Vote announcements will be sent to {channel.mention}")

    @voteconfig.command()
    async def role(self, ctx, role: discord.Role):
        """Set the role given to voters"""
        await self.config.guild(ctx.guild).vote_role.set(role.id)
        await ctx.send(f"Voters will receive the {role.name} role")

    @voteconfig.command()
    async def points(self, ctx, points: int):
        """Set points earned per vote"""
        await self.config.guild(ctx.guild).points_per_vote.set(points)
        await ctx.send(f"Users will earn {points} points per vote")

    @commands.command()
    async def votes(self, ctx, member: discord.Member = None):
        """Check vote points"""
        member = member or ctx.author
        data = await self.config.member(member).all()
        embed = discord.Embed(
            title="Vote Statistics",
            color=discord.Color.purple()
        )
        embed.add_field(name="Total Votes", value=data["total_votes"])
        embed.add_field(name="Vote Points", value=data["vote_points"])
        await ctx.send(embed=embed)

    async def add_vote(self, guild, member):
        """Add a vote for a member"""
        points = await self.config.guild(guild).points_per_vote()
        async with self.config.member(member).all() as data:
            data["vote_points"] += points
            data["total_votes"] += 1

        role_id = await self.config.guild(guild).vote_role()
        if role_id:
            role = guild.get_role(role_id)
            if role and role not in member.roles:
                await member.add_roles(role)

        channel_id = await self.config.guild(guild).vote_channel()
        if channel_id:
            channel = guild.get_channel(channel_id)
            if channel:
                embed = discord.Embed(
                    title="New Vote!",
                    description=f"{member.mention} voted for the server!\nThey earned {points} points!",
                    color=discord.Color.purple()
                )
                await channel.send(embed=embed)

def setup(bot):
    bot.add_cog(VoteTracker(bot))
