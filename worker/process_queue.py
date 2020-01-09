import json, aioredis, discord
#from generator.gpt2.gpt2_generator import *

client = discord.Client()

@client.event
async def on_ready():
    # connect & clear redis queue
    queue = await aioredis.create_connection(os.getenv('REDIS_URL'))
    while await queue.llen('pending'):
        await queue.brpoplpush('pending', 'msgs')

    while True:
        # poll queue for messages, block here if empty
        message = await queue.brpoplpush('msgs', 'pending')
        args = json.loads(message)
        channel, text = args['channel'], args['text']

        # send response, delete message from queue
        response = 'Test response'
        await client.get_channel(channel).send(response)
        await queue.lrem('pending', -1, message)


if __name__ == '__main__':
    client.run(os.getenv('DISCORD_TOKEN'))
