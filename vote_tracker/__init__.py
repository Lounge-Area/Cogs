from .vote_tracker import VoteTracker

async def setup(bot):
    await bot.add_cog(VoteTracker(bot))