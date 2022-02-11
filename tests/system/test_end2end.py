import pytest
from .http_client import run_queries

# TODO: remove hardcoded docker service hostname 'web'.
PREFIX = 'http://web:8000/lookup?key='

def test_end2end_empty_db():
    keys = [i for i in range(10)]
    # TODO: remove 
    urls = (f'{PREFIX}{key}' for key in keys)
    json_results = []
    run_queries(urls, json_results)
    assert len(json_results) == len(keys)
    for i in range(len(keys)):
        r = json_results[i]
        assert r['key'] == str(keys[i]) 
        assert r['value'] == None
        assert r['status'] == 404
