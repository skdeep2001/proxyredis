import argparse
from concurrent.futures import ThreadPoolExecutor
import os
import signal
import sys
import time
import threading

from proxycache.http_server import AsyncHTTPServer
from proxycache.lrucache import LRUCache
from proxycache.rate_limiter import Limiter

# Hack for testing
class Cache:
    def __init__(self):
        pass

    def get(self, key):
        #print("New thread: GET " + req.path)
        return 'Hello from different thread {}: lookup {}'.format(
            threading.get_ident(), key)

def setup_signal_handlers(server):
    def signal_handler(signal, frame):
        server.stop()

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

def get_service_config():
    try:
        return(
                os.environ['PROXY_HOST'],
                int(os.environ['PROXY_PORT']),
                int(os.environ['PROXY_MAX_KEYS']),
                int(os.environ['PROXY_TTL_MS']))
    except Exception:
        print('Unable to find server config settings')
        sys.exit(1)

def get_redis_config():
    try:
        return (
            os.environ['REDIS_HOST'],
            int(os.environ['REDIS_PORT']))
    except Exception:
        print('Unable to find server host/port settings')
        sys.exit(1)
    

def main():
    service_cfg = get_service_config()
    redis_cfg = get_redis_config()
    
    import redis
    r = redis.Redis(host=redis_cfg[0], port=redis_cfg[1], db=0)

    cache = LRUCache(service_cfg[2], service_cfg[3], r)
    cache_executor = ThreadPoolExecutor(max_workers=1)

    rate_limiter = Limiter()

    httpd = AsyncHTTPServer(service_cfg[0], service_cfg[1],
                            cache.get, cache_executor, rate_limiter)
    setup_signal_handlers(httpd)

    # start the server event loop on its own thread
    httpd_thread = threading.Thread(target=httpd.run)
    httpd_thread.start()
    while httpd.is_running():
        time.sleep(0.2)

    httpd_thread.join()

if __name__ == '__main__':
    main()