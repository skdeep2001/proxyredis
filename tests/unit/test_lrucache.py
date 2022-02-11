
from proxycache.lrucache import LRUCache

# TODO: test expiry

class MockDb:
    def __init__(self):
        self.keys = set()
        self.hits = 0

    def get(self, key):
        self.keys.add(key)
        self.hits += 1
        return key

def test_lru_small():
    db = MockDb()
    # cache smaller than working set
    lru = LRUCache(1, 1000, db)
    query_keys = [i for i in range(10)]
    for i in query_keys:
        value = lru.get(i)
        assert value == i
    
    # every query results in db being hit due to
    # compulsory cache miss
    assert lru.hits == 0
    assert lru.misses == len(query_keys)
    assert db.hits == len(query_keys)
    db_keys = list(db.keys)
    assert db_keys == query_keys

    for i in query_keys:
        value = lru.get(i)
        assert value == i
    
    # should see same keys but twice the number of hits
    # since the query pattern results in every query causing
    # cache eviction and capacity miss
    assert lru.hits == 0
    assert lru.misses == len(query_keys) * 2    
    assert db.hits == len(query_keys) * 2
    db_keys = list(db.keys)
    assert db_keys == query_keys

def test_lru_large():
    db = MockDb()
    # cache larger than working set
    lru = LRUCache(10, 1000, db)
    query_keys = [i for i in range(10)]
    for i in query_keys:
        value = lru.get(i)
        assert value == i
    
    assert lru.hits == 0
    assert lru.misses == len(query_keys)    
    assert db.hits == len(query_keys)
    db_keys = list(db.keys)
    assert db_keys == query_keys

    for i in query_keys:
        value = lru.get(i)
        assert value == i
    
    assert lru.hits == len(query_keys)
    assert lru.misses == len(query_keys)    
    assert db.hits == len(query_keys)
    db_keys = list(db.keys)
    assert db_keys == query_keys