from .identitytheft import IdentityTheft

async def setup(bot):
    await bot.add_cog(IdentityTheft(bot))