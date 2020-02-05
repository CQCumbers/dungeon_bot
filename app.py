import os, sys, json, asyncio, logging, traceback
import aiohttp, aioredis, discord
from discord.ext import commands

api_url = 'https://vast.ai/api/v0'
image = 'cqcumbers/dungeon_worker:0.1.3'
timeout, max_msgs = 600, 4
act = discord.Game(name='!help for commands')
desc = 'View the source code at github.com/CQCumbers/dungeon_bot'
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
        'reliability2': {'gte': 0.90}, 'allocated_storage': 15.0,
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
    bot.inst_id = data['instances'][0]['id']
    print(f'Created instance {bot.inst_id}')
    bot.check_inst = bot.loop.create_task(check_inst(180))


async def restart_inst(session, insts):
    # send start instance request to first in list
    bot.inst_id, data = insts[0]['id'], {'state': 'running'}
    await send(session, f'{api_url}/instances/{bot.inst_id}/', data)
    print(f'Restarted instance {bot.inst_id}')
    bot.check_inst = bot.loop.create_task(check_inst(90))


async def workers():
    clients = await bot.queue.client_list()
    return [c for c in clients if c.name != 'server' and int(c.idle) < 60]


async def check_inst(wait):
    await asyncio.sleep(wait)
    while len(await workers()) >= 1: await asyncio.sleep(60)
    # destroy and recreate instance if unconnected
    async with aiohttp.ClientSession() as session:
        url = f'{api_url}/instances/{bot.inst_id}/'
        params = {'api_key': os.getenv('API_KEY')}
        await session.delete(url, params=params)
        print(f'Destroyed instance {bot.inst_id}')
        bot.inst_id = 1234567890; bot.stop_inst.cancel()
        await create_inst(session)
        bot.stop_inst = bot.loop.create_task(stop_inst())


async def stop_inst():
    # wait until no activity and past timeout
    while bot.loop.time() < bot.stop_time: await asyncio.sleep(1)
    # stop instance if no activity for 10 minutes
    async with aiohttp.ClientSession() as session:
        data = {'state': 'stopped'}
        await send(session, f'{api_url}/instances/{bot.inst_id}/', data)
        print(f'Stopped instance {bot.inst_id}')
        bot.inst_id = None; bot.check_inst.cancel()


async def init_inst(ctx):
    bot.inst_id = 1234567890
    await ctx.send('Initializing instance, please wait')
    # reboot instance, or create one if none exists
    async with aiohttp.ClientSession() as session:
        data = await fetch(session, f'{api_url}/instances', {'owner': 'me'})
        insts = data.get('instances')
        await restart_inst(session, insts) if insts else await create_inst(session) 
        bot.stop_inst = bot.loop.create_task(stop_inst())


async def init_queue():
    bot.queue = await aioredis.create_redis_pool(os.getenv('REDIS_URL'))
    await bot.queue.client_setname('server')


@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.errors.CommandNotFound): return
    if isinstance(error.__context__, aiohttp.ContentTypeError): bot.inst_id = None
    print('Ignoring exception in command {}:'.format(ctx.command), file=sys.stderr)
    traceback.print_exception(type(error), error, error.__traceback__, file=sys.stderr)


@bot.command(name='next', help='Continues AI Dungeon game')
async def game_next(ctx, *, text='continue'):
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
