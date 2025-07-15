import argparse
from datetime import datetime, timezone
import dateparser
from discord.ext.commands.converter import (
    ColourConverter,
    EmojiConverter,
    MemberConverter,
    RoleConverter,
    TextChannelConverter,
)
from redbot.core.commands import BadArgument, Converter
from redbot.core.commands.converter import TimedeltaConverter
from .menu import BUTTON_STYLE

class NoExitParser(argparse.ArgumentParser):
    def error(self, message):
        raise BadArgument()

class Args(Converter):
    async def convert(self, ctx, argument):
        argument = argument.replace("—", "--")
        parser = NoExitParser(description="Giveaway Creation", add_help=False)

        # Required Arguments
        parser.add_argument("--prize", "--p", dest="prize", nargs="*", default=[])
        parser.add_argument("--winners", dest="winners", default=1, type=int, nargs="?")
        parser.add_argument("--description", dest="description", default=[], nargs="*")
        timer = parser.add_mutually_exclusive_group()
        timer.add_argument("--duration", "--d", dest="duration", nargs="*", default=[])
        timer.add_argument("--end", "--e", dest="end", nargs="*", default=[])

        # Optional Arguments
        parser.add_argument("--channel", dest="channel", default=None, nargs="?")
        parser.add_argument("--roles", "--r", "--restrict", dest="roles", nargs="*", default=[])
        parser.add_argument("--multiplier", "--m", dest="multiplier", default=None, type=int, nargs="?")
        parser.add_argument("--multi-roles", "--mr", nargs="*", dest="multi_roles", default=[])
        parser.add_argument("--joined", dest="joined_days", default=None, type=int, nargs="?")
        parser.add_argument("--created", dest="account_age_days", default=None, type=int, nargs="?")
        parser.add_argument("--blacklist", dest="blacklist", nargs="*", default=[])
        parser.add_argument("--mentions", dest="mentions", nargs="*", default=[])
        parser.add_argument("--button-text", dest="button-text", default=[], nargs="*")
        parser.add_argument("--button-style", dest="button-style", default=[], nargs="*")
        parser.add_argument("--emoji", dest="emoji", default=None, nargs="*")
        parser.add_argument("--image", dest="image", default=None, nargs="*")
        parser.add_argument("--thumbnail", dest="thumbnail", default=None, nargs="*")
        parser.add_argument("--hosted-by", dest="hosted-by", default=None, nargs="*")
        parser.add_argument("--colour", dest="colour", default=None, nargs="*")
        parser.add_argument("--bypass-roles", nargs="*", dest="bypass_roles", default=[])
        parser.add_argument("--bypass-type", dest="bypass_type", default=None, nargs="?")

        # Setting Arguments
        parser.add_argument("--multientry", action="store_true")
        parser.add_argument("--notify", action="store_true")
        parser.add_argument("--congratulate", action="store_true")
        parser.add_argument("--announce", action="store_true")
        parser.add_argument("--ateveryone", action="store_true")
        parser.add_argument("--athere", action="store_true")
        parser.add_argument("--show-requirements", action="store_true")
        parser.add_argument("--update-button", action="store_true")

        try:
            vals = vars(parser.parse_args(argument.split(" ")))
        except Exception as error:
            raise BadArgument("Could not parse flags correctly, ensure flags are correctly used.") from error

        if not vals["prize"]:
            raise BadArgument("You must specify a prize. Use `--prize` or `-p`")
        if not any([vals["duration"], vals["end"]]) and not ctx.command.name == "add_old":
            raise BadArgument("You must specify a duration or end date. Use `--duration` or `-d` or `--end` or `-e`")

        nums = [vals["winners"], vals["joined_days"], vals["account_age_days"]]
        for val in nums:
            if val is None:
                continue
            if val < 1:
                raise BadArgument("Number must be greater than 0")

        valid_roles = []
        for role in vals["roles"]:
            try:
                role = await RoleConverter().convert(ctx, role)
                valid_roles.append(role.id)
            except BadArgument:
                raise BadArgument(f"The role {role} does not exist within this server.")
        vals["roles"] = valid_roles

        valid_multi_roles = []
        for role in vals["multi_roles"]:
            try:
                role = await RoleConverter().convert(ctx, role)
                valid_multi_roles.append(role.id)
            except BadArgument:
                raise BadArgument(f"The role {role} does not exist within this server.")
        vals["multi_roles"] = valid_multi_roles

        valid_bypass_roles = []
        for role in vals["bypass_roles"]:
            try:
                role = await RoleConverter().convert(ctx, role)
                valid_bypass_roles.append(role.id)
            except BadArgument:
                raise BadArgument(f"The role {role} does not exist within this server.")
        vals["bypass_roles"] = valid_bypass_roles

        valid_blacklist = []
        for role in vals["blacklist"]:
            try:
                role = await RoleConverter().convert(ctx, role)
                valid_blacklist.append(role.id)
            except BadArgument:
                raise BadArgument(f"The role {role} does not exist within this server.")
        vals["blacklist"] = valid_blacklist

        valid_mentions = []
        for role in vals["mentions"]:
            try:
                role = await RoleConverter().convert(ctx, role)
                valid_mentions.append(role.id)
            except BadArgument:
                raise BadArgument(f"The role {role} does not exist within this server.")
        vals["mentions"] = valid_mentions

        if vals["channel"]:
            try:
                vals["channel"] = await TextChannelConverter().convert(ctx, vals["channel"])
            except BadArgument:
                raise BadArgument("Invalid channel.")

        if vals["bypass_type"] and vals["bypass_type"] not in ["or", "and"]:
            raise BadArgument("Bypass type must be either `or` or `and` - default is `or`")

        if (vals["multiplier"] or vals["multi_roles"]) and not (vals["multiplier"] and vals["multi_roles"]):
            raise BadArgument("You must specify both multiplier and multi-roles.")

        if (vals["ateveryone"] or vals["athere"]) and not ctx.channel.permissions_for(ctx.me).mention_everyone:
            raise BadArgument("Bot requires Mention Everyone permission for @everyone or @here.")

        if vals["description"]:
            vals["description"] = " ".join(vals["description"])
            if len(vals["description"]) > 1000:
                raise BadArgument("Description must be less than 1000 characters.")

        if vals["button-text"]:
            vals["button-text"] = " ".join(vals["button-text"])
            if len(vals["button-text"]) > 70:
                raise BadArgument("Button text must be less than 70 characters.")
        else:
            vals["button-text"] = "Join Giveaway"

        if vals["button-style"]:
            vals["button-style"] = " ".join(vals["button-style"]).lower()
            if vals["button-style"] not in BUTTON_STYLE:
                raise BadArgument(f"Button style must be one of: {', '.join(BUTTON_STYLE.keys())}")
        else:
            vals["button-style"] = "green"

        if vals["hosted-by"]:
            vals["hosted-by"] = " ".join(vals["hosted-by"])
            try:
                user = await MemberConverter().convert(ctx, vals["hosted-by"])
                vals["hosted-by"] = user.id
            except BadArgument:
                raise BadArgument("Invalid user.")

        if vals["colour"]:
            vals["colour"] = " ".join(vals["colour"]).lower()
            try:
                vals["colour"] = await ColourConverter().convert(ctx, vals["colour"])
            except Exception:
                raise BadArgument("Invalid colour.")

        if vals["emoji"]:
            vals["emoji"] = " ".join(vals["emoji"]).rstrip().lstrip()
            custom = False
            try:
                vals["emoji"] = await EmojiConverter().convert(ctx, vals["emoji"])
                custom = True
            except Exception:
                vals["emoji"] = str(vals["emoji"]).replace("\N{VARIATION SELECTOR-16}", "")
            try:
                await ctx.message.add_reaction(vals["emoji"])
                await ctx.message.remove_reaction(vals["emoji"], ctx.me)
            except Exception:
                raise BadArgument("Invalid emoji.")
            if custom:
                vals["emoji"] = vals["emoji"].id

        vals["prize"] = " ".join(vals["prize"])
        if vals["duration"]:
            try:
                duration = await TimedeltaConverter().convert(ctx, " ".join(vals["duration"]))
                vals["duration"] = duration
            except BadArgument:
                raise BadArgument("Invalid duration. Use `--duration` or `-d`")
            else:
                if duration.total_seconds() < 60:
                    raise BadArgument("Duration must be greater than 60 seconds.")
        elif vals["end"]:
            try:
                time = dateparser.parse(" ".join(vals["end"]))
                if time.tzinfo is None:
                    time = time.replace(tzinfo=timezone.utc)
                if datetime.now(timezone.utc) > time:
                    raise BadArgument("End date must be in the future.")
                time = time - datetime.now(timezone.utc)
                vals["duration"] = time
                if time.total_seconds() < 60:
                    raise BadArgument("End date must be at least 1 minute in the future.")
            except Exception:
                raise BadArgument("Invalid end date. Use `--end` or `-e`. Ensure to pass a timezone, otherwise it defaults to UTC.")
        
        vals["image"] = " ".join(vals["image"]) if vals["image"] else None
        vals["thumbnail"] = " ".join(vals["thumbnail"]) if vals["thumbnail"] else None
        return vals