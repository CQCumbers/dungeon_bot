import os, json, asyncio, signal, logging
import aiohttp, aioredis
from discord.ext import commands

api_url = 'https://vast.ai/api/v0'
image = 'cqcumbers/dungeon_worker:0.1.1'
timeout, max_msgs = 60.0, 20
bot = commands.Bot(command_prefix='!')


async def fetch(session, url, params={}):
    params['api_key'] = os.getenv('API_KEY')
    async with session.get(url, params=params) as r:
        return await r.json()


async def send(session, url, data, params={}):
    params['api_key'] = os.getenv('API_KEY')
    await session.put(url, params=params, json=data)


async def create_inst(session):
    # Query available machines
    params = {'q': json.dumps({
        'verified': {'eq': True},
        'external': {'eq': False},
        'rentable': {'eq': True},
        'cuda_max_good': {'gte': 10.0},
        'inet_up': {'gte': 100.0},
        'reliability2': {'gte': 0.97},
        'storage': 10.0, 'type': 'on-demand',
        'order': [['dph_total', 'asc']],
    })}
    data = await fetch(session, f'{api_url}/bundles', params)
    bot.inst_id = data['offers'][0]['id']

    # Create instance using cheapest machine
    onstart = (
        f'REDIS_URL={os.getenv("REDIS_URL")}\n'
        f'DISCORD_TOKEN={os.getenv("DISCORD_TOKEN")}\n'
        f'python process_queue.py\n')
    config = {
        'client_id': 'me', 'image': image,
        'runtype': 'ssh', 'disk': 10.0,
        'label': 'dungeon_worker', 'onstart': onstart,
    }
    await send(session, f'{api_url}/asks/{bot.inst_id}/', config)


async def restart_inst(session, insts):
    bot.inst_id, data = insts[0]['id'], {'state': 'running'}
    await send(session, f'{api_url}/instances/{bot.inst_id}/', data)


async def stop_inst(session):
    while asyncio.get_event_loop().time() < bot.stop_time:
        await asyncio.sleep(1)
    data = {'state': 'stopped'}
    await send(session, f'{api_url}/instances/{bot.inst_id}/', data)
    bot.inst_id = None


async def init_inst():
    # reboot instance, or create one if none exists
    async with aiohttp.ClientSession() as session:
        data = await fetch(session, f'{api_url}/instances', {'owner': 'me'})
        insts = data.get('instances')
        await restart_inst(session, insts) if insts else await create_inst(session) 
        bot.stop_time = asyncio.get_event_loop().time() + timeout
        #await stop_inst(session)


async def send_msg(message):
    queue = await aioredis.create_redis_pool(os.getenv('REDIS_URL'))
    if await queue.llen('msgs') < max_msgs:
        await queue.lpush('msgs', json.dumps(message))
    bot.stop_time = asyncio.get_event_loop().time() + timeout
    await init_inst() if not bot.inst_id else None


@bot.command(name='next', help='Continues AI Dungeon game')
async def game_next(ctx, *, text):
    async with ctx.typing():
        await send_msg({'channel': ctx.channel.id, 'text': text})


#@bot.command(name='restart', help='Starts the game from beginning')
#async def game_restart(ctx):
#    send_msg(json.dumps({'channel': ctx.channel.id, 'action': 'restart'}))


#@bot.command(name='revert', help='Undoes the last action')
#async def game_revert(ctx):
#    send_msg(json.dumps({'channel': ctx.channel.id, 'action': 'undo'}))


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    bot.inst_id = None
    bot.run(os.getenv('DISCORD_TOKEN'))
