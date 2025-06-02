# Lounge-Cogs

A collection of cogs for Red-DiscordBot, created by the Lounge Discord server.

## Support

- Website: [http://loungecove.com/](http://loungecove.com/)
- Email: support@loungecove.com
- Discord: [Join our server](https://discord.gg/mTUduyJ2Kq)

## Cogs

### IdentityTheft

Responds to 'I'm ...' messages with humorous identity theft responses. If a user correctly identifies themselves (by mention or text name), the bot says 'Hey Name!'. Otherwise, it triggers impersonation responses via webhooks.

#### Features
- Detects 'I'm ...' messages and verifies user identity by mention (e.g., 'I'm @Floo') or text name (e.g., 'I'm Floo')
- Responds with 'Hey Name!' for correct self-identification
- Uses webhooks for humorous impersonation responses when claiming to be someone else
- Configurable cooldown and blacklist
- Toggleable via commands

#### Commands
- `[p]identitytheft enable` - Toggle automatic responses
- `[p]identitytheft cooldown <seconds>` - Set response cooldown
- `[p]identitytheft blacklist optout` - Opt out of webhook impersonation
- `[p]identitytheft blacklist optin` - Opt in to webhook impersonation

## Installation

To install these cogs, follow these steps:





Add the repository:
```
[p]repo add lounge-cogs https://github.com/Lounge-Area/Cogs
```

Install the desired cog:
```
[p]cog install lounge-cogs identitytheft
```




Load the cog:
```
[p]load IdentityTheft
```

## License

This project is licensed under the MIT License - see the LICENSE file for details.