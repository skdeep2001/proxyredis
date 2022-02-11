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

```
End-to-end benchmark with **wrk** where the key does not exist in the db or cache, so effectively each query will result in hitting the Redis db. Since there is only 1 spare core for the client load generator, we use 1 thread only but ramp up the number of open connections. 
  - For one connection the latency is lowest, and as the number of outstanding connections are increased the latency increases. This is expected since the request processor is single threaded and the bottleneck. 
 - The request throughput seems to peak at around 32 connections and shows that the HTTPD frontend is able to handle concurrent connections.
```
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
The same test with just the HTTP frontend and a dummy cache shows ~3.5-4K requests/sec.
Need to do more performance bottleneck analysis.
