# Lounge-Cogs

A collection of cogs for Red-DiscordBot, created by the Lounge Discord server.

## Support

- Website: [http://loungecove.com/](http://loungecove.com/)
- Email: support@loungecove.com
- Discord: [Join our server](https://discord.gg/mTUduyJ2Kq)

## Cogs

### ModWhitelist

Whitelist specific channels to prevent all bot moderation actions, such as message deletion by any cog, by restoring deleted messages.

#### Features
- Whitelist channels to bypass all moderation actions
- Restores messages deleted by any moderation cog in whitelisted channels
- Configurable via commands
- List and manage whitelisted channels

#### Commands
- `[p]addwhitelist #channel` - Add a channel to the moderation whitelist
- `[p]removewhitelist #channel` - Remove a channel from the whitelist
- `[p]listwhitelist` - List all whitelisted channels

## Installation

To install these cogs, follow these steps:

1. Add the repository:
```
[p]repo add lounge-cogs https://github.com/Lounge-Area/Cogs
```

2. Install the desired cog:
```
[p]cog install lounge-cogs modwhitelist
```

3. Load the cog:
```
[p]load ModWhitelist
```

## License

This project is licensed under the MIT License - see the LICENSE file for details.