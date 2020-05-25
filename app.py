import os, sys, json, asyncio, logging, traceback
import aiohttp, aioredis, discord
from discord.ext import commands

api_url = 'https://vast.ai/api/v0'
image = 'cqcumbers/dungeon_worker:0.1.4'
timeout, max_msgs = 900, 4
act = discord.Game(name='!help for commands')
desc = '''
View the source code at github.com/CQCumbers/dungeon_bot.
For security issues or other questions, message CQCumbers#6058.
'''
bot = commands.Bot(command_prefix='!', activity=act, description=desc)


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
        'verified': {'eq': True}, 'external': {'eq': False},
        'rentable': {'eq': True}, 'disk_space': {'gte': 15.0},
        'gpu_ram': {'gte': 10.0 * 1024}, 'inet_up': {'gte': 100.0},
        'reliability2': {'gte': 0.98}, 'allocated_storage': 15.0,
        'dlperf': {'gte': 9.8}, 'type': 'ask', 'order': [['dphtotal', 'asc']],
    })}
    data = await fetch(session, f'{api_url}/bundles', params)
    offer_id = data['offers'][0]['id']

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
    await send(session, f'{api_url}/asks/{offer_id}/', config)
    data = await fetch(session, f'{api_url}/instances', {'owner': 'me'})
    bot.inst = data['instances'][-1]['id']
    print(f'Created instance {bot.inst}')


async def start_inst(session, insts):
    # send start instance request to last in list
    if not insts: return await create_inst(session)
    bot.inst, data = insts[-1]['id'], {'state': 'running'}
    await send(session, f'{api_url}/instances/{bot.inst}/', data)
    print(f'Restarted instance {bot.inst}')


async def delete_inst(session):
    # send delete request to all instances
    data = await fetch(session, f'{api_url}/instances', {'owner': 'me'})
    for inst in data.get('instances'):
        url = f'{api_url}/instances/{inst["id"]}/'
        params = {'api_key': os.getenv('API_KEY')}
        await session.delete(url, params=params)


async def workers():
    clients = await bot.queue.client_list()
    return len([c for c in clients if c.name != 'server' and int(c.idle) < 60])


async def recreate_inst():
    # destroy and recreate instance if unconnected
    print(f'Destroying instance {bot.inst}')
    async with aiohttp.ClientSession() as session:
        await delete_inst(session)
        await create_inst(session)
    await asyncio.sleep(120)


async def check_inst():
    await asyncio.sleep(180)
    # wait until no activity and past timeout
    while bot.loop.time() < bot.stop_time:
        if await workers() < 1: await recreate_inst()
        await asyncio.sleep(60)
    # stop instance if no activity for 15 minutes
    async with aiohttp.ClientSession() as session:
        url = f'{api_url}/instances/{bot.inst}/'
        await send(session, url, data={'state': 'stopped'})
    print(f'Stopped instance {bot.inst}'); bot.inst = None


async def init_inst(ctx):
    await ctx.send('Initializing instance, please wait')
    if bot.inst is not None: return; bot.inst = 0
    # restart instance, start checkup task
    async with aiohttp.ClientSession() as session:
        data = await fetch(session, f'{api_url}/instances', {'owner': 'me'})
        await start_inst(session, data.get('instances'))
    bot.check = bot.loop.create_task(check_inst())


async def init_queue():
    bot.queue = await aioredis.create_redis_pool(os.getenv('REDIS_URL'))
    await bot.queue.client_setname('server')


@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.errors.CommandNotFound): return
    traceback.print_exception(type(error), error, error.__traceback__)
    if bot.inst == 0: bot.inst = None


@bot.command(name='next', help='Continues AI Dungeon game')
async def game_next(ctx, *, text='continue'):
    message = {'channel': ctx.channel.id, 'text': text}
    bot.stop_time = bot.loop.time() + timeout

    if not bot.queue: await init_queue()
    await bot.queue.setnx(f'{ctx.channel.id}_msgs', 0)
    if int(await bot.queue.get(f'{ctx.channel.id}_msgs')) < max_msgs:
        await bot.queue.incr(f'{ctx.channel.id}_msgs')
        await bot.queue.lpush('msgs', json.dumps(message))
    if await workers() < 1: await init_inst(ctx)


@bot.command(name='restart', help='Starts the game from beginning')
async def game_restart(ctx):
    if not bot.queue: await init_queue()
    await bot.queue.delete(ctx.channel.id)
    await ctx.send('Restarted game from beginning')


@bot.command(name='revert', help='Undoes the last action')
async def game_revert(ctx):
    if not bot.queue: await init_queue()
    await bot.queue.rpop(ctx.channel.id)
    await ctx.send('Undid last action')


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    bot.inst, bot.queue = None, None
    bot.run(os.getenv('DISCORD_TOKEN'))
