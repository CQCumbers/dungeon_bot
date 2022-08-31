import os, re, logging, asyncio
import aiohttp, disnake, redis.asyncio
from logging.handlers import SysLogHandler
from transformers import AutoTokenizer, AutoModelForCausalLM

tokenizer = AutoTokenizer.from_pretrained('./fairseq-dense-2.7B')
model = AutoModelForCausalLM.from_pretrained('./fairseq-dense-2.7B')
model = model.to('cuda:0')
logger = logging.getLogger()


def setup_logger():
    log_host, log_port = os.getenv('LOG_URL').rsplit(':', 1)
    syslog = SysLogHandler(address=(log_host, int(log_port)))
    log_format = '%(asctime)s vast-ai dungeon_worker: %(message)s'
    log_formatter = logging.Formatter(log_format, datefmt='%b %d %H:%M:%S')
    syslog.setFormatter(log_formatter)

    logger.addHandler(syslog)
    logger.setLevel(logging.INFO)
    logger.info('Logger initialized')


# atomically read hook, text, and mem
pull_script = '''
local h = redis.call("GET", KEYS[1])
local t = redis.call("LRANGE", KEYS[2], 0, -1)
local m = redis.call("GET", KEYS[3])
return { h, t, m }
'''

# verify hook unchanged, push and trim output
push_script = '''
if redis.call("GET", KEYS[1]) ~= ARGV[1] then return 0 end
redis.call("DEL", KEYS[1])
redis.call("RPUSH", KEYS[2], ARGV[2])
redis.call("LTRIM", KEYS[2], -18, -1)
return 1
'''

# verify hook unchanged, delete hook and cancel
error_script = '''
if redis.call("GET", KEYS[1]) ~= ARGV[1] then return 0 end
redis.call("DEL", KEYS[1])
redis.call("RPOP", KEYS[2], h and 1 or 0])
'''

async def init_queue():
    logger.info('Connecting to redis')
    queue = await redis.asyncio.from_url(os.getenv('REDIS_URL'), decode_responses=True)
    await queue.client_setname('worker')
    queue.run_pull = queue.register_script(pull_script)
    queue.run_push = queue.register_script(push_script)
    queue.run_error = queue.register_script(error_script)
    logger.info('Registered redis scripts')
    return queue


async def hook_send(hook, embed=None, content=None):
    async with aiohttp.ClientSession() as session:
        wid, token = hook.split(',')
        webhook = disnake.Webhook.partial(wid, token, session=session)
        await webhook.send(embed=embed, content=content)


def generate(input_str):
    input_ids = tokenizer.encode(input_str, return_tensors='pt')
    input_ids = input_ids[..., -160:].to('cuda:0')
    output_ids = model.generate(input_ids, min_length=input_ids.shape[-1] + 20,
        do_sample=True, max_length=200, top_k=50, top_p=0.95)
    output_ids = output_ids[0][..., input_ids.shape[-1]:]
    return tokenizer.decode(output_ids, skip_special_tokens=True)


async def main():
    # connect and clear redis queue
    queue = await init_queue()
    while await queue.llen('pending'):
        await queue.rpoplpush('pending', 'msgs')
    loop = asyncio.get_event_loop()
    logger.info('Waiting for first message')

    while True:
        # poll queue for messages, block here if empty
        cid = await queue.brpoplpush('msgs', 'pending', 60)
        if cid is None: continue
        keys = [f'{cid}_hook', f'{cid}_text', f'{cid}_mem']
        hook, text, mem = await queue.run_pull(keys=keys)
        if not hook or len(text) == 0: continue

        try:
            # construct input and generate response
            logger.info(f'Input for {cid}:\n{text[-1]}')
            task = loop.run_in_executor(None, generate, str(mem) + ''.join(text))
            response = await asyncio.wait_for(task, 60, loop=loop)
            logger.info(f'Output for {cid}:\n{response}')

            # check if cancelled during processing
            # update history, send discord reponse
            keys, args = [f'{cid}_hook', f'{cid}_text'], [hook, response]
            if await queue.run_push(keys=keys, args=args):
                embed = disnake.Embed(description=f'**{text[-1]}**{response}', color=0)
                await hook_send(hook, embed=embed)
        except Exception:
            # cancel and send discord error
            logger.info('Error with message: ', exc_info=True)
            if await queue.run_error(keys=[f'{cid}_hook', f'{cid}_text'], args=[hook]):
                await hook_send(hook, content='Action cancelled by inference failure')

        # delete message from queue
        await queue.lrem('pending', -1, cid)


if __name__ == '__main__':
    setup_logger()
    asyncio.run(main())
