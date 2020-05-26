import os, sys, json, asyncio, logging, traceback
import aiohttp, aioredis, discord
from discord.ext import commands

api_url = 'https://vast.ai/api/v0'
image = 'cqcumbers/dungeon_worker:0.1.4'
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
        'gpu_ram': {'gte': 10.0 * 1000}, 'inet_down': {'gte': 100.0},
        'reliability2': {'gte': 0.9}, 'allocated_storage': 15.0,
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
    machine = data['instances'][-1]['machine_id']
    print(f'Created instance on {machine}')


async def delete_inst(session):
    # send delete request to all instances
    print(f'Destroying all instances')
    data = await fetch(session, f'{api_url}/instances', {'owner': 'me'})
    for inst in data.get('instances'):
        url = f'{api_url}/instances/{inst["id"]}/'
        params = {'api_key': os.getenv('API_KEY')}
        await session.delete(url, params=params)


async def recreate_inst():
    # destroy and recreate instance if unconnected
    async with aiohttp.ClientSession() as session:
        await delete_inst(session)
        await create_inst(session)
    await asyncio.sleep(120)


async def check_inst():
    # workers should poll queue every minute
    def worker(client):
        res = (client.name != 'server')
        return res and int(client.idle) <= 60

    # repeatedly check if workers connected
    while True:
        clients = await bot.queue.client_list()
        workers = [c for c in clients if worker(c)]
        if len(workers) == 0: await recreate_inst()
        await asyncio.sleep(60)


async def init_queue():
    bot.queue = await aioredis.create_redis_pool(os.getenv('REDIS_URL'))
    await bot.queue.client_setname('server')


@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.errors.CommandNotFound): return
    traceback.print_exception(type(error), error, error.__traceback__)


@bot.command(name='next', help='Continues AI Dungeon game')
async def game_next(ctx, *, text='continue'):
    message = {'channel': ctx.channel.id, 'text': text}
    await bot.queue.setnx(f'{ctx.channel.id}_msgs', 0)
    if int(await bot.queue.get(f'{ctx.channel.id}_msgs')) < 4:
        await bot.queue.incr(f'{ctx.channel.id}_msgs')
        await bot.queue.lpush('msgs', json.dumps(message))


@bot.command(name='restart', help='Starts the game from beginning')
async def game_restart(ctx):
    await bot.queue.delete(ctx.channel.id)
    await ctx.send('Restarted game from beginning')


@bot.command(name='revert', help='Undoes the last action')
async def game_revert(ctx):
    await bot.queue.rpop(ctx.channel.id)
    await ctx.send('Undid last action')


if __name__ == '__main__':
    # setup queue and background task
    setup = bot.loop.create_task(init_queue())
    bot.loop.run_until_complete(setup)
    check = bot.loop.create_task(check_inst())

    # start handling discord events
    logging.basicConfig(level=logging.INFO)
    bot.run(os.getenv('DISCORD_TOKEN'))
