from .cleanup_giveaways import CleanupGiveaways

async def setup(bot):
    await bot.add_cog(CleanupGiveaways(bot))