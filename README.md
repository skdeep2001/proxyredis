# ProxyRedis

## Architecture and Code Details
The caching proxy for redis has the following high level architecture:
```
LB(*) -> HTTPD [ -> Throttle] -> Req Processor (LRU Cache -> Redis store)
```
- LB: HTTP Load Balancer that can spray the incoming requests in a round-robin fashion across multiple TCP ports. In the current implementation the load balancer is actually omitted as explained by the next item but is included for scaling up, if a single http server becomes the bottleneck. If/when the Redis protocol on the frontend is implemented, we can support one set of ports to be load balanced that support HTTP and another that support the Redis protocol.
- HTTPD: HTTP server that runs an async event loop in its dedicated thread. The server accepts incoming connections on a single TCP port. It configures the API routes and handles the GET request to query the key from the cache.
  - For scaling, multiple of these servers can be spun up, each bound to a distinct TCP port and running its own async event loop on a dedicated thread/core. When this is done, the load balancer can be added.
  - In the current implementation, only a single port and HTTP server is configured and spun up. Changes to support multiple servers require a minor tweak to the configuration parameter format in the **env** file and a minor change to the main program to create multiple threads and Http server objects.
- Throttle: This is used to implement API rate limiting with the idea of maintaining a backlog that does not grow too large.
  - The current implementation is a dummy stub that does nothing.
- Req Processor: This is the part that multiplexes incoming requests (from potentially multiple HTTPs) and executes the cache get on potentially multiple threads that query the LRUCache and Redis store. The separate threads are to prevent the async event loop from getting stuck as it allows either non-blocking or blocking code to be used in the Request processor.
    - In the current implementation this is accomplished by using a ThreadPoolExecutor. While considering options for decoupling the HTTP request serving and cache querying, having an explicit thread-safe multi-producer/single-consumer queue pair for request/response was considered but ultimately not implemented. The felxibility of the Async IO APIs allowed a simpler implementation using the ThreadPolExecutor.
    - In the current implementation the LRUCache is not thread-safe and so the ThreadPoolExecutor uses a single worker. All incoming requests then are serialzed on this single processing thread.
    - For scaling, assuming the availability of a thread-safe LRU cache implementation, requires a minor tweak to bump up the number of worker threads in the pool and this pool size can also be configured externally at start up time by adding another parameter to the **env** file.
- LRU Cache: This is a pure data structure that implements a cache of limited size with expiring keys. Keys that are not present in the cache will be attempted to be queried from the backing store, a single Redis instance. Expired keys are deleted lazily i.e. when the get for that key is issued. 
    - This potentially uses up memory if there are a lot of expired keys sitting around. An option would be to have a priority queue (min-heap) for expiring nodes and on every cache query keys could be expired (in a batched fashion to amortize the expense). Another option would be to have a reaper thread that is periodically harvesting expired keys and their associated values to reclaim memory but this requires more careful thread safe design.
    - In the current implementation the LRU Cache is not thread-safe.
    - It is implemented using a doubly linked list + hash table. The hash table support O(1) lookup/insertion/deletion of keys. The hash table maps keys to node object references. The node objects that have the key and value are stored in a doubly linked list to support O(1) removal (lookups, expired keys), move-to-head operations (successful lookups or when getting the data from the redis store) as well as remove-from-tail operations to maintain the maximum keys requirement.
- Redis Store: Uses the redis protocol to query Redis db in a synchronous fashion. The option to use the asynchronous version of the interface was not investigated due to lack of time.

## Code
- The code is implemented using Python 3.10. The following libraries are required (installed using pip):
  - redis-py
  - aiohttp (async http library)
  - pytest (for unit and system tests)
- The configuration settings for the services are passed through environment variables defined in the **\<root>/env** file:
  ```
  PROXY_HOST=""
  PROXY_PORT=8000
  PROXY_MAX_KEYS=1000
  PROXY_TTL_MS=10000

  REDIS_HOST=redis
  REDIS_PORT=6379
  ```
- **\<root>/src/proxycache/** has all modules that implement the caching proxy.
  - **\<root>/src/proxycache/main.py** implements the entry point for the service startup and configuration and constructs the processing pipeline shown in the architecture section.

- The HTTP service (**\<root>/src/proxycache/http_server.py**) supports the following GET query:
  ```
  /lookup?key=<key>
  ```
- The result of a properly formatted lookup is returned as JSON response with the following format:
  ```
   {key:<key>, value: <value>, status: <200|404|503|400>}
  ```
  - A successful lookup will return status 200
  - A badly formatted query will return status 400
  - A result of getting throttled with have status 503
  - If a key does not exist in the Redis store (or cache), the status will be 404.
  - The value if it exists will be decoded to a utf-8 string.
- The stub API throttle is defined in **\<root>/src/proxycache/rate_limiter.py**
- A single connection to the db (**\<root>/src/proxycache/db.py**) is kept open for the life of the process.
- Unit and system tests can be found in **\<root>/tests/unit** and **\<root>/tests/system**.
- The **\<root>/Dockerfile** uses a multi stage pattern to build the application container, run the unit tests (during build) and run system tests after containers are running. The **\<root>/docker-compose.yaml** introduces an additional service to ensure the dependencies (Redis and Proxy) are up and running before triggering the end to end tests. See also the associated **<root>/Makefile** and the **test** rule.

## Build and Test
- Requirements for build and run
  - docker, docker-compose, make, bash
  - access to internet for docker hub, pip installs etc
- Configuration settings can be changed in the **env** file found in the project root. For now this does not contain any secrets and so can be checked into source control (and why it is not named .env).
- To build and run:
  ```
  cd <project root>
  make test
  ```
  This will run the unit tests, build the appropriate images, start the containers that host the services and then run the system test. 

## Unimplemented
- Concurrent LRU Cache: Bonus feature was not implemented due to lack of time. Relatively simple to refactor with a coarse grained lock in the LRUCache.
- Redis protocol:  Bonus feature was not implemented due to lack of time. This should have better performance since it doesn't have the overhead of HTTP. The plan would be to have add an AsyncRedisr that is assigned to its own thread(s). The design can support both HTTP and Redis together, with the event loops of each being on separate threads.

## Known Issues / Areas for Improvement
- Fix issue with graceful shutdown of the HTTP server causing container take longer to shutdown.
- Add pre-commit git hooks for PEP8 linter
- More comprehensive unit and system tests. For example:
  - Test with different key and value sizes.
  - Test all error responses
  - High load test
- Improve the code documentation including this README.
- Add logging.
- Add error injection mechanisms.
- Add some more decoupling through factory constructors so cache implementations can be configured at service startup. This will help with testing and analyzing performance, alternatively could use monkey patching.
- Change redis connection to connection pool for developing the concurrent LRUCache.
- Harden against exceptions such as the redis service failure and error out gracefully.
- Dump http server/lrucache/db metrics to a stats database (that can be aggregated across multiple cache partitions/shards) and displayed in something like a Grafana dashboard.
- Add versioning to the API
- Add a _GET /stats_ route to retrieve the current HTTP server, LRUCache and DB stats. Should have its own (more aggressive) limiter so that most of the processing horsepower is reserved for the cache lookups.
- Ideally there should be authn (TLS/HTTPS) and authz if this is an external facing API or even inadvertently exposing internal APIs arising from network firewall policy errors. TLS will require lot more servers to handle the same query load as non-secure HTTP and will have higher latency.
- Implement in Go if higher performance is required. This should eliminate any interpreter latency and also allow finer grained resource control such as pinning thread affinity to a specific CPU.

## Time spent
Around 35 hrs were spent on this project.
- 50% was spent on reading up docs for Docker, Redis and Python APIs, preparing the dev environment. Some of this overlapped with architecture planning.
- 20% of time was spent on setting up dev environment, doing mini POCs / experimental code evaluation to decide what paradigm, 3rd party tools to use for the implementation. A lot of it involved doing mini benchmarking that also tied into the design and implementation. (A VM disk corruption triggerd by WIndows update forced reboot also required recreating the entire dev environment, Murphy's Law :))
- 15% of the time was spent on doing the actual code and unit test development using the experimental code as a base and refactoring, cleaning up hacks/shortcuts in POC code.
- 10% of the time was spent on system test and getting docker networking to play nice.
- 5% of the time was spent on documentation.

## Notes
The HTTP server with a stub cache was tested with [**wrk**](https://github.com/wg/wrk) during development to understand the performance of the HTTP frontend with sync vs async frameworks provided by Python. The wrk integration is not included in the repo at this time.

Minimum core count for this setup: HTTPD x n + ReqProcessor x m + Redis x 1. In the current design n=1 and can be increased, m=1 (needs concurrent LRUCache for m > 1) => min core count = 3 since Redis is running on the same server. A few cores should also be required to test the client load generator.

The builds were done in a Ubuntu VM on VirtualBox using a relatively older laptop and 4 cores. However any performance impact is likely limited by the python interpreter overhead, so fine tuning may have limited value.

```
$ lscpu
Architecture:                    x86_64
...
CPU(s):                          4
On-line CPU(s) list:             0-3
Thread(s) per core:              1
Core(s) per socket:              4
Socket(s):                       1
...
Vendor ID:                       GenuineIntel
CPU family:                      6
Model:                           60
Model name:                      Intel(R) Core(TM) i7-4700MQ CPU @ 2.40GHz
Stepping:                        3
CPU MHz:                         2394.464
BogoMIPS:                        4788.92
Hypervisor vendor:               KVM
Virtualization type:             full
L1d cache:                       128 KiB
L1i cache:                       128 KiB
L2 cache:                        1 MiB
L3 cache:                        24 MiB

$ docker --version
Docker version 20.10.12, build e91ed57

$ docker-compose --version
docker-compose version 1.29.2, build 5becea4c

$ uname -a
Linux sandeep-VirtualBox 5.13.0-28-generic #31~20.04.1-Ubuntu SMP Wed Jan 19 14:08:10 UTC 2022 x86_64 x86_64 x86_64 GNU/Linux
```

### End-to-end benchmarks with **wrk**
Since there is only 1 spare core for the client load generator, we use 1 thread only but ramp up the number of open connections. 
  - For one connection the latency is lowest, and as the number of outstanding connections are increased the latency increases. This is expected since the request processor is single threaded and the bottleneck. With increasing connections, the throughput also increases and then later decreases.
  - The first two measurements use a bad query that results in httpd returning an error without dispatching any work to the Req Processor. This eliminates the LRU cache and Redis db effects altogether and measures http server performance.
  - The subsequent tests will either hit the Redis db (LRU cache miss) or hit in the LRU cache. This allows the extra latency of Redis to be ballparked.
  - uvloop, a drop-in replacement for Python's built in asyncio event loop is also compared and in the second case shows that it performs ~30% better in max throughput.

<details><summary>1. Asyncio's event loop + bypassing Req Processor/LRU cache/Redis by using a bad query</summary>
<p>

  ```
  $ curl http://localhost:8000/lookup
  {"key": null, "value": null, "status": 400}

  $ for i in 1 2 4 8 16 32 64 128; do cmd="../wrk/wrk -t1 -c$i -d30 --latency http://localhost:8000/lookup"; echo; echo $cmd; $cmd; echo ====================================================; done

  ../wrk/wrk -t1 -c1 -d30 --latency http://localhost:8000/lookup
  Running 30s test @ http://localhost:8000/lookup
    1 threads and 1 connections
    Thread Stats   Avg      Stdev     Max   +/- Stdev
      Latency   534.15us  705.25us  23.86ms   98.15%
      Req/Sec     2.09k   340.50     2.57k    74.33%
    Latency Distribution
      50%  447.00us
      75%  504.00us
      90%  598.00us
      99%    2.13ms
    62484 requests in 30.01s, 12.51MB read
    Non-2xx or 3xx responses: 62484
  Requests/sec:   2082.13
  Transfer/sec:    427.00KB
  ====================================================

  ../wrk/wrk -t1 -c2 -d30 --latency http://localhost:8000/lookup
  Running 30s test @ http://localhost:8000/lookup
    1 threads and 2 connections
    Thread Stats   Avg      Stdev     Max   +/- Stdev
      Latency   776.03us  365.93us  15.74ms   97.93%
      Req/Sec     2.63k   230.21     2.91k    85.00%
    Latency Distribution
      50%  729.00us
      75%  779.00us
      90%    0.86ms
      99%    1.43ms
    78678 requests in 30.00s, 15.76MB read
    Non-2xx or 3xx responses: 78678
  Requests/sec:   2622.53
  Transfer/sec:    537.82KB
  ====================================================

  ../wrk/wrk -t1 -c4 -d30 --latency http://localhost:8000/lookup
  Running 30s test @ http://localhost:8000/lookup
    1 threads and 4 connections
    Thread Stats   Avg      Stdev     Max   +/- Stdev
      Latency     1.48ms  439.72us  14.06ms   95.12%
      Req/Sec     2.73k   271.56     3.00k    86.71%
    Latency Distribution
      50%    1.40ms
      75%    1.47ms
      90%    1.69ms
      99%    2.85ms
    81859 requests in 30.10s, 16.39MB read
    Non-2xx or 3xx responses: 81859
  Requests/sec:   2719.64
  Transfer/sec:    557.74KB
  ====================================================

  ../wrk/wrk -t1 -c8 -d30 --latency http://localhost:8000/lookup
  Running 30s test @ http://localhost:8000/lookup
    1 threads and 8 connections
    Thread Stats   Avg      Stdev     Max   +/- Stdev
      Latency     2.77ms  506.46us  16.25ms   96.93%
      Req/Sec     2.92k   166.20     3.13k    91.03%
    Latency Distribution
      50%    2.71ms
      75%    2.77ms
      90%    2.85ms
      99%    4.40ms
    87337 requests in 30.10s, 17.49MB read
    Non-2xx or 3xx responses: 87337
  Requests/sec:   2901.59
  Transfer/sec:    595.05KB
  ====================================================

  ../wrk/wrk -t1 -c16 -d30 --latency http://localhost:8000/lookup
  Running 30s test @ http://localhost:8000/lookup
    1 threads and 16 connections
    Thread Stats   Avg      Stdev     Max   +/- Stdev
      Latency     5.49ms    1.15ms  29.12ms   93.95%
      Req/Sec     2.94k   275.33     3.22k    90.67%
    Latency Distribution
      50%    5.26ms
      75%    5.41ms
      90%    5.89ms
      99%   10.65ms
    87885 requests in 30.02s, 17.60MB read
    Non-2xx or 3xx responses: 87885
  Requests/sec:   2927.06
  Transfer/sec:    600.28KB
  ====================================================

  ../wrk/wrk -t1 -c32 -d30 --latency http://localhost:8000/lookup
  Running 30s test @ http://localhost:8000/lookup
    1 threads and 32 connections
    Thread Stats   Avg      Stdev     Max   +/- Stdev
      Latency    11.28ms    1.49ms  32.45ms   92.85%
      Req/Sec     2.85k   255.75     3.17k    86.67%
    Latency Distribution
      50%   11.00ms
      75%   11.24ms
      90%   12.08ms
      99%   18.05ms
    85179 requests in 30.02s, 17.06MB read
    Non-2xx or 3xx responses: 85179
  Requests/sec:   2837.73
  Transfer/sec:    581.96KB
  ====================================================

  ../wrk/wrk -t1 -c64 -d30 --latency http://localhost:8000/lookup
  Running 30s test @ http://localhost:8000/lookup
    1 threads and 64 connections
    Thread Stats   Avg      Stdev     Max   +/- Stdev
      Latency    21.29ms    2.90ms  50.81ms   91.00%
      Req/Sec     3.02k   301.75     3.28k    89.33%
    Latency Distribution
      50%   20.37ms
      75%   21.22ms
      90%   23.90ms
      99%   35.44ms
    90243 requests in 30.02s, 18.07MB read
    Non-2xx or 3xx responses: 90243
  Requests/sec:   3005.94
  Transfer/sec:    616.45KB
  ====================================================

  ../wrk/wrk -t1 -c128 -d30 --latency http://localhost:8000/lookup
  Running 30s test @ http://localhost:8000/lookup
    1 threads and 128 connections
    Thread Stats   Avg      Stdev     Max   +/- Stdev
      Latency    44.96ms    3.63ms  98.61ms   93.34%
      Req/Sec     2.86k   226.46     3.23k    76.00%
    Latency Distribution
      50%   44.28ms
      75%   45.23ms
      90%   46.69ms
      99%   61.50ms
    85398 requests in 30.04s, 17.10MB read
    Non-2xx or 3xx responses: 85398
  Requests/sec:   2842.91
  Transfer/sec:    583.02KB
  ====================================================
  ```
</p>
</details>

<details><summary>2. uvloop's event loop + bypassing Req Processor/LRU cache/Redis by using a bad query</summary>
<p>

  ```
  $ curl http://localhost:8000/lookup
  {"key": null, "value": null, "status": 400}

  $ for i in 1 2 4 8 16 32 64 128; do cmd="../wrk/wrk -t1 -c$i -d30 --latency http://localhost:8000/lookup"; echo; echo $cmd; $cmd; echo ====================================================; done

  ../wrk/wrk -t1 -c1 -d30 --latency http://localhost:8000/lookup
  Running 30s test @ http://localhost:8000/lookup
    1 threads and 1 connections
    Thread Stats   Avg      Stdev     Max   +/- Stdev
      Latency   569.35us  176.67us   7.58ms   93.17%
      Req/Sec     1.77k   249.22     2.25k    56.67%
    Latency Distribution
      50%  545.00us
      75%  620.00us
      90%  708.00us
      99%    0.91ms
    52885 requests in 30.00s, 10.59MB read
    Non-2xx or 3xx responses: 52885
  Requests/sec:   1762.81
  Transfer/sec:    361.51KB
  ====================================================

  ../wrk/wrk -t1 -c2 -d30 --latency http://localhost:8000/lookup
  Running 30s test @ http://localhost:8000/lookup
    1 threads and 2 connections
    Thread Stats   Avg      Stdev     Max   +/- Stdev
      Latency   702.13us  490.04us  19.26ms   97.80%
      Req/Sec     2.97k   445.94     3.45k    77.33%
    Latency Distribution
      50%  614.00us
      75%  694.00us
      90%    0.89ms
      99%    1.82ms
    88766 requests in 30.00s, 17.78MB read
    Non-2xx or 3xx responses: 88766
  Requests/sec:   2958.77
  Transfer/sec:    606.78KB
  ====================================================

  ../wrk/wrk -t1 -c4 -d30 --latency http://localhost:8000/lookup
  Running 30s test @ http://localhost:8000/lookup
    1 threads and 4 connections
    Thread Stats   Avg      Stdev     Max   +/- Stdev
      Latency     1.25ms  701.13us  23.23ms   97.57%
      Req/Sec     3.31k   322.10     3.65k    83.33%
    Latency Distribution
      50%    1.14ms
      75%    1.21ms
      90%    1.37ms
      99%    3.02ms
    98796 requests in 30.00s, 19.79MB read
    Non-2xx or 3xx responses: 98796
  Requests/sec:   3292.70
  Transfer/sec:    675.26KB
  ====================================================

  ../wrk/wrk -t1 -c8 -d30 --latency http://localhost:8000/lookup
  Running 30s test @ http://localhost:8000/lookup
    1 threads and 8 connections
    Thread Stats   Avg      Stdev     Max   +/- Stdev
      Latency     2.35ms  707.26us  13.99ms   92.89%
      Req/Sec     3.42k   457.94     3.92k    87.00%
    Latency Distribution
      50%    2.16ms
      75%    2.30ms
      90%    2.81ms
      99%    5.39ms
    102073 requests in 30.02s, 20.44MB read
    Non-2xx or 3xx responses: 102073
  Requests/sec:   3400.68
  Transfer/sec:    697.41KB
  ====================================================

  ../wrk/wrk -t1 -c16 -d30 --latency http://localhost:8000/lookup
  Running 30s test @ http://localhost:8000/lookup
    1 threads and 16 connections
    Thread Stats   Avg      Stdev     Max   +/- Stdev
      Latency     4.32ms    0.95ms  24.71ms   93.70%
      Req/Sec     3.71k   296.36     4.04k    83.33%
    Latency Distribution
      50%    4.11ms
      75%    4.24ms
      90%    4.74ms
      99%    7.29ms
    110849 requests in 30.05s, 22.20MB read
    Non-2xx or 3xx responses: 110849
  Requests/sec:   3688.80
  Transfer/sec:    756.49KB
  ====================================================

  ../wrk/wrk -t1 -c32 -d30 --latency http://localhost:8000/lookup
  Running 30s test @ http://localhost:8000/lookup
    1 threads and 32 connections
    Thread Stats   Avg      Stdev     Max   +/- Stdev
      Latency     8.32ms    1.30ms  43.65ms   92.45%
      Req/Sec     3.82k   270.97     4.10k    85.67%
    Latency Distribution
      50%    8.06ms
      75%    8.30ms
      90%    8.96ms
      99%   12.73ms
    114372 requests in 30.06s, 22.91MB read
    Non-2xx or 3xx responses: 114372
  Requests/sec:   3804.85
  Transfer/sec:    780.29KB
  ====================================================

  ../wrk/wrk -t1 -c64 -d30 --latency http://localhost:8000/lookup
  Running 30s test @ http://localhost:8000/lookup
    1 threads and 64 connections
    Thread Stats   Avg      Stdev     Max   +/- Stdev
      Latency    16.27ms    2.30ms  76.85ms   88.67%
      Req/Sec     3.91k   287.72     4.30k    87.33%
    Latency Distribution
      50%   15.93ms
      75%   16.50ms
      90%   17.91ms
      99%   22.89ms
    117000 requests in 30.07s, 23.43MB read
    Non-2xx or 3xx responses: 117000
  Requests/sec:   3891.12
  Transfer/sec:    797.98KB
  ====================================================

  ../wrk/wrk -t1 -c128 -d30 --latency http://localhost:8000/lookup
  Running 30s test @ http://localhost:8000/lookup
    1 threads and 128 connections
    Thread Stats   Avg      Stdev     Max   +/- Stdev
      Latency    33.64ms    5.78ms 108.94ms   77.86%
      Req/Sec     3.78k   406.77     4.49k    85.00%
    Latency Distribution
      50%   33.49ms
      75%   35.50ms
      90%   38.82ms
      99%   54.85ms
    113113 requests in 30.08s, 22.65MB read
    Non-2xx or 3xx responses: 113113
  Requests/sec:   3759.84
  Transfer/sec:    771.06KB
  ====================================================
  ```
</p>
</details>

<details><summary>3. Asyncio's event loop + every query accessing Redis db (lru cache miss)</summary>
<p>

  ```
  $ curl http://localhost:8000/lookup?key=20
  {"key": "20", "value": null, "status": 404}
  
  $ for i in 1 2 4 8 16 32 64 128; do cmd="../wrk/wrk -t1 -c$i -d30 --latency http://localhost:8000/lookup?key=20"; echo; echo $cmd; $cmd; echo ====================================================; done

  ../wrk/wrk -t1 -c1 -d30 --latency http://localhost:8000/lookup?key=20
  Running 30s test @ http://localhost:8000/lookup?key=20
    1 threads and 1 connections
    Thread Stats   Avg      Stdev     Max   +/- Stdev
      Latency     1.25ms  305.77us  12.59ms   93.09%
      Req/Sec   806.80     87.34     1.12k    77.67%
    Latency Distribution
      50%    1.25ms
      75%    1.35ms
      90%    1.42ms
      99%    2.09ms
    24115 requests in 30.03s, 4.78MB read
    Non-2xx or 3xx responses: 24115
  Requests/sec:    802.96
  Transfer/sec:    163.10KB
  ====================================================

  ../wrk/wrk -t1 -c2 -d30 --latency http://localhost:8000/lookup?key=20
  Running 30s test @ http://localhost:8000/lookup?key=20
    1 threads and 2 connections
    Thread Stats   Avg      Stdev     Max   +/- Stdev
      Latency     1.65ms  454.06us  14.28ms   88.23%
      Req/Sec     1.23k   162.24     1.48k    68.33%
    Latency Distribution
      50%    1.57ms
      75%    1.79ms
      90%    2.03ms
      99%    3.24ms
    36683 requests in 30.02s, 7.28MB read
    Non-2xx or 3xx responses: 36683
  Requests/sec:   1222.11
  Transfer/sec:    248.24KB
  ====================================================

  ../wrk/wrk -t1 -c4 -d30 --latency http://localhost:8000/lookup?key=20
  Running 30s test @ http://localhost:8000/lookup?key=20
    1 threads and 4 connections
    Thread Stats   Avg      Stdev     Max   +/- Stdev
      Latency     3.02ms  722.05us  18.47ms   85.14%
      Req/Sec     1.33k   152.25     1.59k    68.00%
    Latency Distribution
      50%    2.90ms
      75%    3.25ms
      90%    3.70ms
      99%    5.56ms
    39799 requests in 30.01s, 7.89MB read
    Non-2xx or 3xx responses: 39799
  Requests/sec:   1326.27
  Transfer/sec:    269.40KB
  ====================================================

  ../wrk/wrk -t1 -c8 -d30 --latency http://localhost:8000/lookup?key=20
  Running 30s test @ http://localhost:8000/lookup?key=20
    1 threads and 8 connections
    Thread Stats   Avg      Stdev     Max   +/- Stdev
      Latency     5.70ms    1.27ms  31.67ms   85.81%
      Req/Sec     1.41k   183.95     1.67k    68.67%
    Latency Distribution
      50%    5.41ms
      75%    6.08ms
      90%    6.98ms
      99%   10.11ms
    42200 requests in 30.00s, 8.37MB read
    Non-2xx or 3xx responses: 42200
  Requests/sec:   1406.50
  Transfer/sec:    285.69KB
  ====================================================

  ../wrk/wrk -t1 -c16 -d30 --latency http://localhost:8000/lookup?key=20
  Running 30s test @ http://localhost:8000/lookup?key=20
    1 threads and 16 connections
    Thread Stats   Avg      Stdev     Max   +/- Stdev
      Latency    11.68ms    2.22ms  33.41ms   82.08%
      Req/Sec     1.38k   196.88     1.73k    70.00%
    Latency Distribution
      50%   11.24ms
      75%   12.39ms
      90%   14.01ms
      99%   19.95ms
    41099 requests in 30.00s, 8.15MB read
    Non-2xx or 3xx responses: 41099
  Requests/sec:   1369.85
  Transfer/sec:    278.26KB
  ====================================================

  ../wrk/wrk -t1 -c32 -d30 --latency http://localhost:8000/lookup?key=20
  Running 30s test @ http://localhost:8000/lookup?key=20
    1 threads and 32 connections
    Thread Stats   Avg      Stdev     Max   +/- Stdev
      Latency    24.24ms    6.40ms 111.50ms   90.13%
      Req/Sec     1.34k   235.01     1.81k    73.00%
    Latency Distribution
      50%   23.22ms
      75%   25.02ms
      90%   28.50ms
      99%   49.49ms
    39938 requests in 30.03s, 7.92MB read
    Non-2xx or 3xx responses: 39938
  Requests/sec:   1329.84
  Transfer/sec:    270.12KB
  ====================================================

  ../wrk/wrk -t1 -c64 -d30 --latency http://localhost:8000/lookup?key=20
  Running 30s test @ http://localhost:8000/lookup?key=20
    1 threads and 64 connections
    Thread Stats   Avg      Stdev     Max   +/- Stdev
      Latency    45.08ms    6.17ms 103.81ms   72.82%
      Req/Sec     1.43k   173.26     1.84k    69.00%
    Latency Distribution
      50%   44.40ms
      75%   48.66ms
      90%   52.12ms
      99%   65.66ms
    42571 requests in 30.01s, 8.44MB read
    Non-2xx or 3xx responses: 42571
  Requests/sec:   1418.42
  Transfer/sec:    288.12KB
  ====================================================

  ../wrk/wrk -t1 -c128 -d30 --latency http://localhost:8000/lookup?key=20
  Running 30s test @ http://localhost:8000/lookup?key=20
    1 threads and 128 connections
    Thread Stats   Avg      Stdev     Max   +/- Stdev
      Latency    92.99ms   18.59ms 231.58ms   82.68%
      Req/Sec     1.38k   245.22     1.80k    70.57%
    Latency Distribution
      50%   88.21ms
      75%   98.85ms
      90%  116.89ms
      99%  161.35ms
    41281 requests in 30.02s, 8.19MB read
    Non-2xx or 3xx responses: 41281
  Requests/sec:   1375.30
  Transfer/sec:    279.36KB
  ====================================================
  ```
</p>
</details>

<details><summary>4. uvloop event loop + every query accessing the Redis db (lru cache miss)</summary>
<p>

  ```
  $ curl http://localhost:8000/lookup?key=20
    {"key": "20", "value": null, "status": 404}

  $ for i in 1 2 4 8 16 32 64 128; do cmd="../wrk/wrk -t1 -c$i -d30 --latency http://localhost:8000/lookup?key=20"; echo; echo $cmd; $cmd; echo ====================================================; done

  ../wrk/wrk -t1 -c1 -d30 --latency http://localhost:8000/lookup?key=20
  Running 30s test @ http://localhost:8000/lookup?key=20
    1 threads and 1 connections
    Thread Stats   Avg      Stdev     Max   +/- Stdev
      Latency     1.23ms  344.10us  12.86ms   93.73%
      Req/Sec   823.08    128.56     1.18k    77.00%
    Latency Distribution
      50%    1.25ms
      75%    1.34ms
      90%    1.41ms
      99%    2.18ms
    24608 requests in 30.04s, 4.88MB read
    Non-2xx or 3xx responses: 24608
  Requests/sec:    819.22
  Transfer/sec:    166.40KB
  ====================================================

  ../wrk/wrk -t1 -c2 -d30 --latency http://localhost:8000/lookup?key=20
  Running 30s test @ http://localhost:8000/lookup?key=20
    1 threads and 2 connections
    Thread Stats   Avg      Stdev     Max   +/- Stdev
      Latency     1.56ms  787.17us  23.96ms   98.31%
      Req/Sec     1.33k   127.96     1.69k    71.00%
    Latency Distribution
      50%    1.46ms
      75%    1.60ms
      90%    1.79ms
      99%    3.81ms
    39778 requests in 30.02s, 7.89MB read
    Non-2xx or 3xx responses: 39778
  Requests/sec:   1325.20
  Transfer/sec:    269.18KB
  ====================================================

  ../wrk/wrk -t1 -c4 -d30 --latency http://localhost:8000/lookup?key=20
  Running 30s test @ http://localhost:8000/lookup?key=20
    1 threads and 4 connections
    Thread Stats   Avg      Stdev     Max   +/- Stdev
      Latency     2.80ms  712.26us  20.64ms   94.05%
      Req/Sec     1.45k   170.65     1.81k    75.67%
    Latency Distribution
      50%    2.70ms
      75%    2.94ms
      90%    3.20ms
      99%    5.50ms
    43232 requests in 30.00s, 8.58MB read
    Non-2xx or 3xx responses: 43232
  Requests/sec:   1440.95
  Transfer/sec:    292.69KB
  ====================================================

  ../wrk/wrk -t1 -c8 -d30 --latency http://localhost:8000/lookup?key=20
  Running 30s test @ http://localhost:8000/lookup?key=20
    1 threads and 8 connections
    Thread Stats   Avg      Stdev     Max   +/- Stdev
      Latency     5.37ms    0.89ms  23.55ms   84.98%
      Req/Sec     1.50k   155.81     1.84k    62.00%
    Latency Distribution
      50%    5.23ms
      75%    5.70ms
      90%    6.18ms
      99%    8.24ms
    44762 requests in 30.00s, 8.88MB read
    Non-2xx or 3xx responses: 44762
  Requests/sec:   1491.88
  Transfer/sec:    303.04KB
  ====================================================

  ../wrk/wrk -t1 -c16 -d30 --latency http://localhost:8000/lookup?key=20
  Running 30s test @ http://localhost:8000/lookup?key=20
    1 threads and 16 connections
    Thread Stats   Avg      Stdev     Max   +/- Stdev
      Latency    10.96ms    2.09ms  40.69ms   92.08%
      Req/Sec     1.47k   186.53     1.78k    79.33%
    Latency Distribution
      50%   10.60ms
      75%   11.49ms
      90%   12.36ms
      99%   21.10ms
    43904 requests in 30.00s, 8.71MB read
    Non-2xx or 3xx responses: 43904
  Requests/sec:   1463.27
  Transfer/sec:    297.23KB
  ====================================================

  ../wrk/wrk -t1 -c32 -d30 --latency http://localhost:8000/lookup?key=20
  Running 30s test @ http://localhost:8000/lookup?key=20
    1 threads and 32 connections
    Thread Stats   Avg      Stdev     Max   +/- Stdev
      Latency    22.04ms    2.52ms  49.92ms   73.99%
      Req/Sec     1.46k   134.40     1.77k    67.33%
    Latency Distribution
      50%   21.89ms
      75%   23.27ms
      90%   24.92ms
      99%   30.08ms
    43529 requests in 30.00s, 8.63MB read
    Non-2xx or 3xx responses: 43529
  Requests/sec:   1450.82
  Transfer/sec:    294.70KB
  ====================================================

  ../wrk/wrk -t1 -c64 -d30 --latency http://localhost:8000/lookup?key=20
  Running 30s test @ http://localhost:8000/lookup?key=20
    1 threads and 64 connections
    Thread Stats   Avg      Stdev     Max   +/- Stdev
      Latency    44.41ms    6.92ms 109.75ms   88.63%
      Req/Sec     1.45k   182.65     1.76k    78.33%
    Latency Distribution
      50%   43.35ms
      75%   46.28ms
      90%   50.06ms
      99%   75.78ms
    43257 requests in 30.02s, 8.58MB read
    Non-2xx or 3xx responses: 43257
  Requests/sec:   1440.93
  Transfer/sec:    292.69KB
  ====================================================

  ../wrk/wrk -t1 -c128 -d30 --latency http://localhost:8000/lookup?key=20
  Running 30s test @ http://localhost:8000/lookup?key=20
    1 threads and 128 connections
    Thread Stats   Avg      Stdev     Max   +/- Stdev
      Latency    88.10ms    7.82ms 162.32ms   70.25%
      Req/Sec     1.46k   137.80     1.72k    71.33%
    Latency Distribution
      50%   86.89ms
      75%   91.77ms
      90%   99.52ms
      99%  109.57ms
    43523 requests in 30.01s, 8.63MB read
    Non-2xx or 3xx responses: 43523
  Requests/sec:   1450.16
  Transfer/sec:    294.56KB
  ====================================================
  ```
</p>
</details>

<details><summary>5. Asyncio event loop + every query hitting in lru cache</summary>
<p>

  ```
  curl http://localhost:8000/lookup?key=0
  {"key": "0", "value": "0", "status": 200}
  
  $ for i in 1 2 4 8 16 32 64 128; do cmd="../wrk/wrk -t1 -c$i -d30 --latency http://localhost:8000/lookup?key=0"; echo; echo $cmd; $cmd; echo ====================================================; done

  ../wrk/wrk -t1 -c1 -d30 --latency http://localhost:8000/lookup?key=0
  Running 30s test @ http://localhost:8000/lookup?key=0
    1 threads and 1 connections
    Thread Stats   Avg      Stdev     Max   +/- Stdev
      Latency   805.10us  452.13us  13.56ms   98.53%
      Req/Sec     1.28k   138.94     1.63k    67.67%
    Latency Distribution
      50%  764.00us
      75%  833.00us
      90%    0.92ms
      99%    1.55ms
    38340 requests in 30.00s, 7.28MB read
  Requests/sec:   1277.92
  Transfer/sec:    248.35KB
  ====================================================

  ../wrk/wrk -t1 -c2 -d30 --latency http://localhost:8000/lookup?key=0
  Running 30s test @ http://localhost:8000/lookup?key=0
    1 threads and 2 connections
    Thread Stats   Avg      Stdev     Max   +/- Stdev
      Latency     1.16ms  585.77us  16.60ms   98.56%
      Req/Sec     1.77k   133.82     1.98k    78.67%
    Latency Distribution
      50%    1.11ms
      75%    1.18ms
      90%    1.29ms
      99%    2.12ms
    52866 requests in 30.00s, 10.03MB read
  Requests/sec:   1762.10
  Transfer/sec:    342.44KB
  ====================================================

  ../wrk/wrk -t1 -c4 -d30 --latency http://localhost:8000/lookup?key=0
  Running 30s test @ http://localhost:8000/lookup?key=0
    1 threads and 4 connections
    Thread Stats   Avg      Stdev     Max   +/- Stdev
      Latency     2.16ms    1.10ms  42.54ms   97.42%
      Req/Sec     1.91k   222.50     2.15k    85.33%
    Latency Distribution
      50%    2.01ms
      75%    2.14ms
      90%    2.45ms
      99%    4.90ms
    57085 requests in 30.02s, 10.83MB read
  Requests/sec:   1901.57
  Transfer/sec:    369.54KB
  ====================================================

  ../wrk/wrk -t1 -c8 -d30 --latency http://localhost:8000/lookup?key=0
  Running 30s test @ http://localhost:8000/lookup?key=0
    1 threads and 8 connections
    Thread Stats   Avg      Stdev     Max   +/- Stdev
      Latency     4.05ms  849.94us  19.16ms   86.29%
      Req/Sec     1.99k   229.89     2.29k    77.33%
    Latency Distribution
      50%    3.86ms
      75%    4.21ms
      90%    5.08ms
      99%    6.69ms
    59396 requests in 30.03s, 11.27MB read
  Requests/sec:   1978.06
  Transfer/sec:    384.41KB
  ====================================================

  ../wrk/wrk -t1 -c16 -d30 --latency http://localhost:8000/lookup?key=0
  Running 30s test @ http://localhost:8000/lookup?key=0
    1 threads and 16 connections
    Thread Stats   Avg      Stdev     Max   +/- Stdev
      Latency     7.76ms    1.49ms  32.15ms   90.79%
      Req/Sec     2.08k   199.74     2.36k    82.67%
    Latency Distribution
      50%    7.53ms
      75%    7.89ms
      90%    8.73ms
      99%   13.51ms
    62072 requests in 30.02s, 11.78MB read
  Requests/sec:   2067.42
  Transfer/sec:    401.77KB
  ====================================================

  ../wrk/wrk -t1 -c32 -d30 --latency http://localhost:8000/lookup?key=0
  Running 30s test @ http://localhost:8000/lookup?key=0
    1 threads and 32 connections
    Thread Stats   Avg      Stdev     Max   +/- Stdev
      Latency    14.84ms    2.08ms  43.96ms   90.27%
      Req/Sec     2.17k   164.78     2.40k    82.00%
    Latency Distribution
      50%   14.48ms
      75%   15.24ms
      90%   16.16ms
      99%   24.58ms
    64795 requests in 30.05s, 12.30MB read
  Requests/sec:   2155.94
  Transfer/sec:    418.98KB
  ====================================================
    
  ../wrk/wrk -t1 -c64 -d30 --latency http://localhost:8000/lookup?key=0
  Running 30s test @ http://localhost:8000/lookup?key=0
    1 threads and 64 connections
    Thread Stats   Avg      Stdev     Max   +/- Stdev
      Latency    33.10ms    8.02ms 189.65ms   93.33%
      Req/Sec     1.96k   240.32     2.33k    85.95%
    Latency Distribution
      50%   31.46ms
      75%   32.51ms
      90%   36.01ms
      99%   62.92ms
    58493 requests in 30.04s, 11.10MB read
  Requests/sec:   1947.33
  Transfer/sec:    378.44KB
  ====================================================

  ../wrk/wrk -t1 -c128 -d30 --latency http://localhost:8000/lookup?key=0
  Running 30s test @ http://localhost:8000/lookup?key=0
    1 threads and 128 connections
    Thread Stats   Avg      Stdev     Max   +/- Stdev
      Latency    62.34ms    4.97ms  97.00ms   87.62%
      Req/Sec     2.06k   174.82     2.55k    75.00%
    Latency Distribution
      50%   61.15ms
      75%   62.65ms
      90%   66.68ms
      99%   80.81ms
    61611 requests in 30.06s, 11.69MB read
  Requests/sec:   2049.54
  Transfer/sec:    398.30KB
  ====================================================
  ```
</p>
</details>

<details><summary>6. uvloop event loop + hitting in lru cache.</summary>
<p>

  ```
  $ curl http://localhost:8000/lookup?key=0
    {"key": "0", "value": "0", "status": 200}

  $ for i in 1 2 4 8 16 32 64 128; do cmd="../wrk/wrk -t1 -c$i -d30 --latency http://localhost:8000/lookup?key=0"; echo; echo $cmd; $cmd; echo ====================================================; done

  ../wrk/wrk -t1 -c1 -d30 --latency http://localhost:8000/lookup?key=0
  Running 30s test @ http://localhost:8000/lookup?key=0
    1 threads and 1 connections
    Thread Stats   Avg      Stdev     Max   +/- Stdev
      Latency   817.12us  432.51us  13.05ms   96.57%
      Req/Sec     1.27k   235.57     1.60k    67.67%
    Latency Distribution
      50%  739.00us
      75%  825.00us
      90%    1.03ms
      99%    2.33ms
    37896 requests in 30.02s, 7.19MB read
  Requests/sec:   1262.49
  Transfer/sec:    245.35KB
  ====================================================

  ../wrk/wrk -t1 -c2 -d30 --latency http://localhost:8000/lookup?key=0
  Running 30s test @ http://localhost:8000/lookup?key=0
    1 threads and 2 connections
    Thread Stats   Avg      Stdev     Max   +/- Stdev
      Latency     1.18ms  657.86us  21.50ms   98.65%
      Req/Sec     1.75k   135.40     2.00k    73.67%
    Latency Distribution
      50%    1.13ms
      75%    1.20ms
      90%    1.29ms
      99%    2.42ms
    52198 requests in 30.02s, 9.91MB read
  Requests/sec:   1738.49
  Transfer/sec:    337.85KB
  ====================================================

  ../wrk/wrk -t1 -c4 -d30 --latency http://localhost:8000/lookup?key=0
  Running 30s test @ http://localhost:8000/lookup?key=0
    1 threads and 4 connections
    Thread Stats   Avg      Stdev     Max   +/- Stdev
      Latency     1.92ms  611.57us  19.08ms   97.48%
      Req/Sec     2.10k   124.85     2.30k    79.33%
    Latency Distribution
      50%    1.87ms
      75%    1.98ms
      90%    2.10ms
      99%    3.43ms
    62879 requests in 30.03s, 11.93MB read
  Requests/sec:   2094.07
  Transfer/sec:    406.95KB
  ====================================================

  ../wrk/wrk -t1 -c8 -d30 --latency http://localhost:8000/lookup?key=0
  Running 30s test @ http://localhost:8000/lookup?key=0
    1 threads and 8 connections
    Thread Stats   Avg      Stdev     Max   +/- Stdev
      Latency     3.18ms    0.88ms  25.31ms   93.99%
      Req/Sec     2.52k   175.65     2.85k    80.00%
    Latency Distribution
      50%    3.12ms
      75%    3.36ms
      90%    3.65ms
      99%    5.48ms
    75319 requests in 30.04s, 14.29MB read
  Requests/sec:   2507.46
  Transfer/sec:    487.29KB
  ====================================================

  ../wrk/wrk -t1 -c16 -d30 --latency http://localhost:8000/lookup?key=0
  Running 30s test @ http://localhost:8000/lookup?key=0
    1 threads and 16 connections
    Thread Stats   Avg      Stdev     Max   +/- Stdev
      Latency     5.93ms    1.13ms  26.73ms   89.59%
      Req/Sec     2.69k   157.88     2.92k    76.67%
    Latency Distribution
      50%    5.78ms
      75%    6.28ms
      90%    6.77ms
      99%    9.43ms
    80340 requests in 30.04s, 15.25MB read
  Requests/sec:   2674.29
  Transfer/sec:    519.71KB
  ====================================================

  ../wrk/wrk -t1 -c32 -d30 --latency http://localhost:8000/lookup?key=0
  Running 30s test @ http://localhost:8000/lookup?key=0
    1 threads and 32 connections
    Thread Stats   Avg      Stdev     Max   +/- Stdev
      Latency    12.19ms    2.43ms  54.02ms   87.14%
      Req/Sec     2.61k   209.63     2.94k    74.00%
    Latency Distribution
      50%   11.96ms
      75%   12.85ms
      90%   13.92ms
      99%   21.84ms
    78053 requests in 30.05s, 14.81MB read
  Requests/sec:   2597.39
  Transfer/sec:    504.77KB
  ====================================================

  ../wrk/wrk -t1 -c64 -d30 --latency http://localhost:8000/lookup?key=0
  Running 30s test @ http://localhost:8000/lookup?key=0
    1 threads and 64 connections
    Thread Stats   Avg      Stdev     Max   +/- Stdev
      Latency    25.79ms    4.81ms  88.98ms   82.69%
      Req/Sec     2.48k   266.63     3.20k    76.33%
    Latency Distribution
      50%   25.20ms
      75%   27.51ms
      90%   30.51ms
      99%   42.70ms
    74046 requests in 30.06s, 14.05MB read
  Requests/sec:   2463.09
  Transfer/sec:    478.67KB
  ====================================================

  ../wrk/wrk -t1 -c128 -d30 --latency http://localhost:8000/lookup?key=0
  Running 30s test @ http://localhost:8000/lookup?key=0
    1 threads and 128 connections
    Thread Stats   Avg      Stdev     Max   +/- Stdev
      Latency    56.18ms    6.89ms 109.51ms   79.16%
      Req/Sec     2.28k   253.31     2.86k    67.33%
    Latency Distribution
      50%   54.92ms
      75%   58.79ms
      90%   64.60ms
      99%   78.91ms
    68237 requests in 30.09s, 12.95MB read
  Requests/sec:   2267.68
  Transfer/sec:    440.69KB
  ====================================================
  ```
</p>
</details>

Need to do more performance bottleneck analysis.
