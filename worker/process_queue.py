import os, re, json, logging, asyncio, aioredis
from discord import Client, Intents
from generator.gpt2.gpt2_generator import *
from logging.handlers import SysLogHandler

log_host, log_port = os.getenv('LOG_URL').rsplit(':', 1)
syslog = SysLogHandler(address=(log_host, int(log_port)))
log_format = '%(asctime)s vast-ai dungeon_worker: %(message)s'
log_formatter = logging.Formatter(log_format, datefmt='%b %d %H:%M:%S')
syslog.setFormatter(log_formatter)

logger = logging.getLogger()
logger.addHandler(syslog)
logger.setLevel(logging.INFO)

import tensorflow as tf
tf.compat.v1.logging.set_verbosity(tf.compat.v1.logging.DEBUG)

max_history = 20
generator = GPT2Generator()
client = Client(intents=Intents.default())
logger.info('Worker instance started')


def escape(text):
    text = re.sub(r'\\(\*|_|`|~|\\|>)', r'\g<1>', text)
    return re.sub(r'(\*|_|`|~|\\|>)', r'\\\g<1>', text)


@client.event
async def on_ready():
    # connect & clear redis queue
    logger.info('Connecting to redis')
    queue = await aioredis.create_redis_pool(os.getenv('REDIS_URL'))
    await queue.client_setname('worker')
    loop = asyncio.get_event_loop()
    while await queue.llen('pending'):
        await queue.rpoplpush('pending', 'msgs')
    logger.info('Waiting for first message')

    while True:
        # poll queue for messages, block here if empty
        msg = None
        while not msg: msg = await queue.brpoplpush('msgs', 'pending', 10)
        logger.info(f'Processing message: {msg}'); args = json.loads(msg)
        channel, text = args['channel'], f'\n> {args["text"]}\n'

        # generate response, update conversation history
        try:
            async with client.get_channel(channel).typing():
                history = await queue.lrange(channel, 0, max_history - 1)
                task = loop.run_in_executor(
                    None, generator.generate, ''.join(history + [text]))
                response = await asyncio.wait_for(task, 60, loop=loop)
                await queue.rpush(channel, text, response)
                await queue.ltrim(channel, -max_history, -1)
                await queue.expire(channel, 7 * 24 * 3600)
                sent = f'> {args["text"]}\n{escape(response)}'
                await client.get_channel(channel).send(sent)
        except Exception:
            logger.info('Error with message: ', exc_info=True)

        # delete message from queue
        await queue.decr(f'{channel}_msgs')
        await queue.lrem('pending', -1, msg)


if __name__ == '__main__':
    client.run(os.getenv('DISCORD_TOKEN'))
