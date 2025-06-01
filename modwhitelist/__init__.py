from .modwhitelist import ModWhitelist

async def setup(bot):
    await bot.add_cog(ModWhitelist(bot))