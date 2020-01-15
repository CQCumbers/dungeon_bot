# Dungeon Bot
> AI Dungeon 2 Discord Bot

An experiment with running web services on vast.ai. `REDIS_URL` and `REDIS_EXTERN_URL` point to same redis, but latter is exposed and visible from workers. To update worker code, build and push worker image to docker hub, and repeat changes on instance via ssh. If you'd prefer not to host it yourself, you can add a hosted instance to your server [here](https://discordapp.com/oauth2/authorize?client_id=664915224595398666&permissions=0&scope=bot)

## Commands
- `!help` - Shows information about commands
- `!next [text]` - Continues AI Dungeon game
- `!restart` - Starts the game from beginning
- `!revert` - Undoes the last action
