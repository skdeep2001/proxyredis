import redis

class KVStore:
    def __init__(self, host, port):
        self.host = host
        self.port = port
        self.hits = 0
        self.misses = 0
        self.errors = 0

    def get(self, key):
        raise NotImplementedError

class RedisKVStore(KVStore):
    def __init__(self, host, port):
        super().__init__(host, port)
        self.db = redis.Redis(host=host, port=port, db=0)

    def get(self, key):
        try:
            result = self.db.get(key)
        except Exception as e:
            print(e)
            result = None
            self.errors += 1

        if result is None:
            self.misses += 1
        else:
            # returns bytearray, convert to utf-8
            result = result.decode()
            self.hits += 1
        return result

