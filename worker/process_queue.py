import os, json, asyncio, aioredis, discord
from generator.gpt2.gpt2_generator import *

max_history = 20
client = discord.Client()
generator = GPT2Generator()

@client.event
async def on_ready():
    # connect & clear redis queue
    queue = await aioredis.create_redis(os.getenv('REDIS_URL'))
    loop = asyncio.get_event_loop()
    while await queue.llen('pending'):
        await queue.rpoplpush('pending', 'msgs')

    while True:
        # poll queue for messages, block here if empty
        message = await queue.brpoplpush('msgs', 'pending')
        print(f'Processing message: {message}')
        args = json.loads(message)
        channel, text = args['channel'], f'\n> {args["text"]}\n'

        # generate response, update conversation history
        async with client.get_channel(channel).typing():
            history = await queue.lrange(channel, 0, max_history - 1)
            response = await loop.run_in_executor(
                None, generator.generate, ''.join(history + [text]))
            await queue.rpush(channel, text, response)
            await queue.ltrim(channel, -max_history, -1)

        # send response, delete message from queue
        await client.get_channel(channel).send(response)
        await queue.lrem('pending', -1, message)


if __name__ == '__main__':
    client.run(os.getenv('DISCORD_TOKEN'))
