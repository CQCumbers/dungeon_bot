# hook exists iff text[-1] is user input
# if hook exists, channel in msgs/pending
# mem is deleted when text is deleted

# get all in msgs/pending and delete
clear_script = '''
local a = redis.call("LRANGE", KEYS[1], 0, -1)
local b = redis.call("LRANGE", KEYS[2], 0, -1)
redis.call("DEL", KEYS[1], KEYS[2])
return { a, b }
'''

# get expired stories, remove from set
expire_script = '''
local e = redis.call("ZRANGEBYSCORE", KEYS[1], 0, redis.call("TIME")[1])
if #e > 0 then redis.call("ZREMRANGEBYRANK", KEYS[1], 0, #e - 1) end
return e
'''

# set hook, add user input to text
# add channel to msgs, and update expiry
next_script = '''
if redis.call("SETNX", KEYS[1], ARGV[1]) == 0 then return 0 end
redis.call("RPUSH", KEYS[2], ARGV[2])
redis.call("LPUSH", KEYS[3], ARGV[3])
redis.call("ZADD", KEYS[4], redis.call("TIME")[1] + 604800, ARGV[3])
return 1
'''

# set mem and update expiry
remember_script = '''
redis.call("SET", KEYS[1], ARGV[1])
redis.call("ZADD", KEYS[2], redis.call("TIME")[1] + 604800, ARGV[2])
'''

# delete hook, text, and mem
restart_script = '''
redis.call("DEL", KEYS[2], KEYS[3])
return redis.call("GETDEL", KEYS[1])
'''

# if hook, delete hook and cancel
# otherwise remove last elements from text
undo_script = '''
local h = redis.call("GETDEL", KEYS[1])
redis.call("RPOP", KEYS[2], h and 1 or ARGV[1])
return h
'''

def register_scripts(queue):
    queue.run_clear = queue.register_script(clear_script)
    queue.run_expire = queue.register_script(expire_script)
    queue.run_next = queue.register_script(next_script)
    queue.run_remember = queue.register_script(remember_script)
    queue.run_restart = queue.register_script(restart_script)
    queue.run_undo = queue.register_script(undo_script)

