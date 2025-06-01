# Lounge-Cogs

A collection of cogs for Red-DiscordBot, created by the Lounge Discord server.

## Support

- Website: [http://loungecove.com/](http://loungecove.com/)
- Email: support@loungecove.com
- Discord: [Join our server](https://discord.gg/loungecove)

## Cogs

### ModWhitelist

Whitelist specific channels to exclude them from bot moderation actions, such as message deletion or automated filtering.

#### Features
- Whitelist channels to bypass moderation
- Configurable via commands
- List and manage whitelisted channels
- Prevents message deletion and other moderation actions in specified channels

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