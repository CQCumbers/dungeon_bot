# Dungeon Bot
> AI Dungeon 2 Discord Bot

Dungeon Bot brings the open-ended text adventure experience of AI Dungeon 2 to Discord, allowing people to craft interesting GPT-2 generated narratives together with other users in the same channel. This is an unofficial bot based on the original open source [AI Dungeon 2](https://github.com/AIDungeon/AIDungeon), and is not kept up to date with new closed-source releases.

[Add it to your server!](https://discordapp.com/oauth2/authorize?client_id=664915224595398666&scope=bot)

Incoming requests are handled by `app.py`, which then sends prompts to a vast.ai GPU worker running `process_queue.py` for inference. `REDIS_URL` and `REDIS_EXTERN_URL` should point to the same redis instance. To update worker code, build and push worker image to docker hub, and repeat changes on instance via ssh.

## Commands
- `!help` - Shows information about commands
- `!next [text]` - Continues AI Dungeon game
- `!restart` - Starts the game from beginning
- `!revert` - Undoes the last action
