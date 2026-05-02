from redis import Redis
from rq import Queue

from app.settings import env, env_int

REDIS_HOST = env("REDIS_HOST", "localhost")
REDIS_PORT = env_int("REDIS_PORT", 6379)

redis_conn = Redis(host=REDIS_HOST, port=REDIS_PORT, db=0)
queue = Queue("meetings", connection=redis_conn)
