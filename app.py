import os, json, asyncio, signal, logging
import aiohttp, aioredis
from discord.ext import commands

api_url = 'https://vast.ai/api/v0'
image = 'cqcumbers/dungeon_worker:0.1.3'
timeout, max_msgs = 600.0, 4
bot = commands.Bot(command_prefix='!')


async def fetch(session, url, params={}):
    params['api_key'] = os.getenv('API_KEY')
    async with session.get(url, params=params) as r:
        return await r.json()


async def send(session, url, data, params={}):
    params['api_key'] = os.getenv('API_KEY')
    await session.put(url, params=params, json=data)


async def create_inst(session):
    bot.inst_id = 123456789
    # Query available machines
    params = {'q': json.dumps({
        'verified': {'eq': True}, 'external': {'eq': False},
        'rentable': {'eq': True}, 'disk_space': {'gte': 15.0},
        'gpu_ram': {'gte': 10.0 * 1024}, 'inet_up': {'gte': 100.0},
        'reliability2': {'gte': 0.90}, 'allocated_storage': 15.0,
        'dlperf': {'gte': 9.8}, 'type': 'ask', 'order': [['dphtotal', 'asc']],
    })}
    data = await fetch(session, f'{api_url}/bundles', params)
    bot.inst_id = data['offers'][0]['id']

    # Create instance using cheapest machine
    onstart = (
        f'export REDIS_URL={os.getenv("REDIS_EXTERN_URL")}\n'
        f'export DISCORD_TOKEN={os.getenv("DISCORD_TOKEN")}\n'
        f'export LOG_URL={os.getenv("LOG_URL")}\n'
        f'cd / && python process_queue.py\n')
    config = {
        'client_id': 'me', 'image': image,
        'runtype': 'ssh', 'disk': 15.0,
        'label': 'dungeon_worker', 'onstart': onstart,
    }
    await send(session, f'{api_url}/asks/{bot.inst_id}/', config)
    print(f'Created instance {bot.inst_id}')


async def restart_inst(session, insts):
    # send start instance request to first in list
    bot.inst_id, data = insts[0]['id'], {'state': 'running'}
    await send(session, f'{api_url}/instances/{bot.inst_id}/', data)
    print(f'Restarted instance {bot.inst_id}')
    bot.destroy_inst = bot.loop.create_task(destroy_inst())


async def stop_inst():
    # wait until no activity and past timeout
    while bot.loop.time() < bot.stop_time:
        await asyncio.sleep(1.0)
    # send stop instance request
    async with aiohttp.ClientSession() as session:
        data = {'state': 'stopped'}
        await send(session, f'{api_url}/instances/{bot.inst_id}/', data)
        print(f'Stopped instance {bot.inst_id}'); bot.inst_id = None


async def destroy_inst():
    await asyncio.sleep(60.0)
    async with aiohttp.ClientSession() as session:
        data = await fetch(session, f'{api_url}/instances', {'owner': 'me'})
        url = f'{api_url}/instances/{bot.inst_id}/'
        params = {'api_key': os.getenv('API_KEY')}
        if data['instances'][0]['actual_status'] != 'running':
            await session.delete(url, params=params)
            print(f'Destroyed instance {bot.inst_id}')
            bot.inst_id = None; await create_inst(session)


async def init_inst(ctx):
    await ctx.send('Initializing instance, please wait')
    # reboot instance, or create one if none exists
    async with aiohttp.ClientSession() as session:
        data = await fetch(session, f'{api_url}/instances', {'owner': 'me'})
        insts = data.get('instances')
        await restart_inst(session, insts) if insts else await create_inst(session) 
        bot.stop_inst = bot.loop.create_task(stop_inst())


async def init_queue():
    bot.queue = await aioredis.create_redis_pool(os.getenv('REDIS_URL'))


@bot.command(name='next', help='Continues AI Dungeon game')
async def game_next(ctx, *, text):
    message = {'channel': ctx.channel.id, 'text': text}
    bot.stop_time = bot.loop.time() + timeout

    await init_queue() if not bot.queue else None
    await bot.queue.setnx(f'{ctx.channel.id}_msgs', 0)
    if int(await bot.queue.get(f'{ctx.channel.id}_msgs')) < max_msgs:
        await bot.queue.incr(f'{ctx.channel.id}_msgs')
        await bot.queue.lpush('msgs', json.dumps(message))
    await init_inst(ctx) if not bot.inst_id else None


@bot.command(name='restart', help='Starts the game from beginning')
async def game_restart(ctx):
    await init_queue() if not bot.queue else None
    await bot.queue.delete(ctx.channel.id)
    await ctx.send('Restarted game from beginning')


@bot.command(name='revert', help='Undoes the last action')
async def game_revert(ctx):
    await init_queue() if not bot.queue else None
    await bot.queue.rpop(ctx.channel.id)
    await ctx.send('Undid last action')


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    bot.inst_id, bot.queue = None, None
    bot.run(os.getenv('DISCORD_TOKEN'))
