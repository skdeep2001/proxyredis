import pytest
import redis
from .http_client import run_queries

# TODO: remove hardcoded docker service hostname 'web'.
PREFIX = 'http://web:8000/lookup?key='

def populate_db(key_values):
    # TODO: remove hardcoded docker service hostname 'redis', port id.
    r = redis.Redis(host='redis', port=6379, db=0)
    for kv in key_values:
        assert r.set(kv[0], kv[1])

def test_end2end_empty_db():
    keys = [i for i in range(10)]
    urls = (f'{PREFIX}{key}' for key in keys)
    json_results = []
    run_queries(urls, json_results)
    assert len(json_results) == len(keys)
    for i in range(len(keys)):
        r = json_results[i]
        assert r['key'] == str(keys[i]) 
        assert r['value'] == None
        assert r['status'] == 404

def test_end2end_populated_db():
    keys = [i for i in range(10)]
    key_values = [(str(k), str(k*10000)) for k in keys]
    populate_db(key_values)

    urls = (f'{PREFIX}{key}' for key in keys)
    json_results = []
    run_queries(urls, json_results)
    assert len(json_results) == len(keys)
    for i in range(len(keys)):
        r = json_results[i]
        assert r['key'] == str(keys[i]) 
        assert r['value'] == key_values[i][1]
        assert r['status'] == 200

