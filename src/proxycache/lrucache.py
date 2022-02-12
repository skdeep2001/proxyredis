'''Implements a read-only LRU cache of fixed capacity.
Keys not found in the cache will be attempted to be
fetched from a backing store.
Each key is associated with a time to live (ttl).
Once the ttl has expired the value will have to be
retrieved from the backing store.
Expired keys are deleted lazily in this implementation.
This potentially can hold on to memory longer than needed.
'''

import time 
from proxycache.linkedlist import (LinkedList, Node)

milli_to_nano = 1000000

class ExpiringCache:
    def __init__(self):
        self.hits = 0
        self.misses = 0
        self.capacity_evictions = 0
        self.expiry_evictions = 0

class LRUCache(ExpiringCache):
    def __init__(self, max_keys, ttl_ms, db):
        super().__init__()
        self.max_keys = max_keys
        self.ttl_ms = ttl_ms
        self.db = db

        self.map = dict()
        self.list = LinkedList()
    
    def _expiry_time(self):
        return time.time_ns() + self.ttl_ms * milli_to_nano

    def _put(self, key, value):
        assert key not in self.map
            
        if len(self.map) >= self.max_keys:
            last = self.list.tail
            self.list.remove(last)
            del self.map[last.key]
            self.capacity_evictions += 1

        node = Node(key, value)
        node.expiry = self._expiry_time()
        self.list.add_to_head(node)
        self.map[key] = node
        return node

    def get(self, key):
        # print('LRUCache get key {}'.format(key))
        if key in self.map:
            node = self.map[key]
            
            if time.time_ns() < node.expiry:
                if node != self.list.head:
                    self.list.remove(node)
                    self.list.add_to_head(node)
                self.hits += 1
                return node.value
            else:
                self.list.remove(node)
                del self.map[key]
                self.expiry_evictions += 1
                self.misses += 1

                value = self.db.get(key)
                # print(f'db1 returned key={key} value={value}')
                if value is None:
                    return None

                node.value = value
                node.expiry = self._expiry_time()
                self.map[key] = node
                self.list.add_to_head(node)
                return value
        else:
            value = self.db.get(key)
            # print(f'db2 returned key={key} value={value}')
            if value is None:
                return None
            self.misses += 1
            node = self._put(key, value)
            assert node is not None
            return node.value
