# Lounge-Cogs

A collection of cogs for Red-DiscordBot, created by the Lounge Discord server.

## Support

- Website: [http://loungecove.com/](http://loungecove.com/)
- Email: support@loungecove.com
- Discord: [Join our server](https://discord.gg/loungecove)

## Cogs

### VoteTracker

Track and reward users for voting for your server on various Discord server listing sites.

#### Features
- Track votes per user
- Award points for voting
- Automatic role assignment
- Configurable vote announcements
- Vote statistics command

#### Commands
- `[p]voteconfig channel #channel` - Set the announcement channel
- `[p]voteconfig role @role` - Set the voter role
- `[p]voteconfig points <amount>` - Set points per vote
- `[p]votes [member]` - Check vote statistics

## Installation

To install these cogs, follow these steps:

1. Add the repository:
```
[p]repo add lounge-cogs https://github.com/Lounge-Area/Cogs
```

2. Install the desired cog:
```
[p]cog install lounge-cogs vote_tracker
```

## License

This project is licensed under the MIT License - see the LICENSE file for details.