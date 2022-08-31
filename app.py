import os, json, asyncio, datetime, logging, traceback
import aiohttp, disnake, redis.asyncio
from disnake.ext import commands
from redis_scripts import register_scripts

api_url = 'https://vast.ai/api/v0'
image = 'cqcumbers/dungeon_worker:0.1.6'
act = disnake.Game(name='/about for info')
bot = commands.InteractionBot(activity=act)
logger = logging.getLogger()


def sleepy():
    hour = datetime.datetime.now().hour
    return hour in range(4, 22)


async def fetch(session, url, params={}):
    params['api_key'] = os.getenv('API_KEY')
    async with session.get(url, params=params) as r:
        if r.status == 200: return await r.json()
        logger.info(f'Failed to get {url}: {r.status}')
        return None


async def send(session, url, data, params={}):
    params['api_key'] = os.getenv('API_KEY')
    await session.put(url, params=params, json=data)


async def create_inst(session):
    # Query available machines
    params = {'q': json.dumps({
        'verified': {'eq': True}, 'external': {'eq': False},
        'rentable': {'eq': True}, 'disk_space': {'gte': 15.0},
        'cuda_max_good': {'gte': 11.2}, 'gpu_name': {'eq': 'RTX 3090'},
        'gpu_ram': {'gte': 8.0 * 1000}, 'inet_down': {'gte': 100.0},
        'reliability2': {'gte': 0.9}, 'allocated_storage': 15.0,
        'type': 'ask', 'order': [['dphtotal', 'asc']],
    })}
    data = await fetch(session, f'{api_url}/bundles', params)
    if not data: return
    offers = [o for o in data['offers'] if o['machine_id'] != bot.machine]
    offer_id = offers[0]['id']

    # Create instance using cheapest machine
    onstart = (
        f'export REDIS_URL={os.getenv("REDIS_EXTERN_URL")}\n'
        f'export LOG_URL={os.getenv("LOG_URL")}\n'
        f'cd / && python3 process_queue.py\n')
    config = {
        'client_id': 'me', 'image': image,
        'runtype': 'ssh', 'disk': 15.0,
        'label': 'dungeon_worker', 'onstart': onstart,
    }
    await send(session, f'{api_url}/asks/{offer_id}/', config)
    data = await fetch(session, f'{api_url}/instances', {'owner': 'me'})
    if not data: return
    bot.machine = data['instances'][-1]['machine_id']
    logger.info(f'Created instance on {bot.machine}')


async def delete_inst(session):
    # send delete request to all instances
    data = await fetch(session, f'{api_url}/instances', {'owner': 'me'})
    if not data: return 
    for inst in data['instances']:
        logger.info(f'Destroying instance {inst["id"]}')
        url = f'{api_url}/instances/{inst["id"]}/'
        params = {'api_key': os.getenv('API_KEY')}
        await session.delete(url, params=params)


async def recreate_inst(now):
    # destroy and recreate instance if unconnected
    logger.info(f"Recreating instance, time {now}")
    async with aiohttp.ClientSession() as session:
        await delete_inst(session)
        await create_inst(session)
    return now + 360


async def clear_inst(now):
    async with aiohttp.ClientSession() as session:
        await delete_inst(session)
    return now + 600


async def hook_send(hook: str, msg: str):
    async with aiohttp.ClientSession() as session:
        wid, token = hook.split(',')
        webhook = disnake.Webhook.partial(wid, token, session=session)
        await webhook.send(content=msg)


async def clear_hooks():
    channels_a, channels_b = await bot.queue.run_clear(keys=['msgs', 'pending'])
    for cid in channels_a + channels_b:
        logger.info(f'Clearing hook {cid}')
        hook = await bot.queue.run_undo(keys=[f'{cid}_hook', f'{cid}_text'], args=[0])
        if hook: await hook_send(hook, 'Action cancelled by server shutdown')


async def expire_stories():
    channel_ids = await bot.queue.run_expire(keys=['expiry'])
    for cid in channel_ids:
        logger.info(f'Expiring story {cid}')
        hook = await bot.queue.run_restart(keys=[f'{cid}_hook', f'{cid}_text', f'{cid}_mem'])
        if hook: await hook_send(hook, 'Action cancelled by story expiration')


async def check_inst():
    # workers should poll queue every minute
    def worker(client):
        res = (client.get('name') == 'worker')
        return res and int(client['idle']) <= 180

    # repeatedly check if workers connected
    next_clear = next_create = 0
    while True:
        try:
            clients = await bot.queue.client_list()
            bot.workers = sum(1 for c in clients if worker(c))
            if bot.workers == 0: await clear_hooks()
            await expire_stories()

            now, asleep = bot.loop.time(), sleepy()
            if asleep and now > next_clear:
                next_clear = await clear_inst(now)
            if not asleep and bot.workers != 1 and now > next_create:
                next_create = await recreate_inst(now)
        except Exception:
            logger.info(traceback.format_exc())
        await asyncio.sleep(60)


async def init_queue():
    bot.queue = await redis.asyncio.from_url(os.getenv('REDIS_URL'), decode_responses=True)
    await bot.queue.client_setname('server')
    register_scripts(bot.queue)
    logger.info('Registered redis scripts')


@bot.event
async def on_slash_command_error(inter, error):
    lines = traceback.format_exception(type(error), error, error.__traceback__)
    logger.info(''.join(lines))


@bot.slash_command(description='Generate more of the story')
async def next(inter, action: str):
    if bot.workers == 0:
        off_msg = 'asleep' if sleepy() else 'offline'
        return await inter.response.send_message(f'Servers are currently {off_msg}')

    cid = inter.channel_id
    keys = [f'{cid}_hook', f'{cid}_text', 'msgs', 'expiry']
    hook = f'{inter.followup.id},{inter.followup.token}'
    if await bot.queue.run_next(keys=keys, args=[hook, action, cid]):
        return await inter.response.defer()
    await inter.response.send_message('Story is already being generated')


@bot.slash_command(description='Restart the story from the beginning')
async def restart(inter):
    cid = inter.channel_id
    hook = await bot.queue.run_restart(keys=[f'{cid}_hook', f'{cid}_text', f'{cid}_mem'])
    if hook: await hook_send(hook, 'Action cancelled by restart')
    await inter.response.send_message('Restarted story from the beginning')


@bot.slash_command(description='Undo or cancel the most recent action')
async def undo(inter):
    cid = inter.channel_id
    hook = await bot.queue.run_undo(keys=[f'{cid}_hook', f'{cid}_text'], args=[2])
    if hook: await hook_send(hook, 'Action cancelled by undo')
    await inter.response.send_message('Undid last action')


@bot.slash_command(description='Set persistent memories for the current story')
async def remember(inter, memory: str):
    cid = inter.channel_id
    await bot.queue.run_remember(keys=[f'{cid}_mem', 'expiry'], args=[memory, cid])
    await inter.response.send_message('Updated story memory')


about_text = '''
**About**
This is an unofficial bot based on the original open source AI Dungeon 2.
You can use it to play freeform text adventures with others in the same channel.
Note that story history is automatically cleared after a week and anyone can
restart the current story. Servers are currently only online after 6 PM EST,
to reduce hosting costs.

**Links**
[Invite Link](https://discordapp.com/oauth2/authorize?client_id=664915224595398666&scope=bot)
  |  [Source Code](https://github.com/CQCumbers/dungeon_bot)
For privacy issues or other questions message me at CQCumbers#6058
'''

@bot.slash_command(description='Show info about this bot')
async def about(inter):
    embed = disnake.Embed(description=about_text, color=0)
    await inter.response.send_message(embed=embed)


if __name__ == '__main__':
    # setup queue and background task
    setup = bot.loop.create_task(init_queue())
    bot.loop.run_until_complete(setup)
    check = bot.loop.create_task(check_inst())
    bot.machine, bot.workers = 0, 0

    # start handling discord events
    logging.basicConfig(level=logging.INFO)
    bot.run(os.getenv('DISCORD_TOKEN'))
