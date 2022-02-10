# ProxyRedis

## Architecture and Details
The caching proxy for redis has this as its high level architecture:
```
LB(*) -> HTTPD [ -> Throttle] -> Req Processor (LRU Cache -> Redis store)
```
- LB: Load Balancer that can spray the incoming requests in a round-robin fashion across multiple TCP ports. In the current implementation the load balancer is actually omitted as explained by the next item but is included for scaling up, if a signle http server becomes the bottleneck.
- HTTPD: HTTP server that runs an async event loop in its dedicated thread. The server accepts incoming connections on a single TCP port. It configures the API routes and handles the GET request to query the key from the cache.
  - For scaling, multiple of these servers can be spun up, each bound to a distinct TCP port and running its own async event loop on a dedicated thread/core. When this is done, the load balancer can be added.
  - In the current implementation, only a single port and HTTP server is configured and spun up. Changes to support multiple servers require a minor tweak to the configuration parameter format in the **env** file and a minor change to the main program to create multiple threads and Http server objects.
- Req Processor: This is the part that multiplexes incoming requests (from potentially multiple HTTPs) and executes the cache get on potentially multiple threads that query the LRUCache and Redis store. The separate threads are to prevent the async event loop from getting stuck as it allows either non-blocking or blocking code to be used in the Request processor.
    - In the current implementation this is accomplished by using a ThreadPoolExecutor. While considering options for decoupling the HTTP request serving and cache querying, having an explicit thread-safe multi-producer/single-consumer queue pair for request/response was considered but ultimately not implemented. The felxibility of the Async IO APIs allowed a simpler implementation using the ThreadPolExecutor.
    - In the current implementation the LRUCache is not thread-safe and so the ThreadPoolExecutor uses a single worker. All incoming requests then are serialzed on this single processing thread.
    - For scaling, assuming the availability of a thread-safe LRU cache implementation, requires a minor tweak to bump up the number of worker threads in the pool and this pool size can also be configured externally at start up time by adding another parameter to the **env** file.
- LRU Cache: This is a pure data structure that implements a cache of limited size with expiring keys. Keys that are not present in the cache will be attempted to be queried from the backing store, a single Redis instance. Expired keys are deleted lazily i.e. when the get for that key is issued. 
    - This potentially uses up memory if there are a lot of expired keys sitting around. An option would be to have a priority queue (min-heap) for expiring nodes and on every cache query keys could be expired (in a batched fashion to amortize the expense). Another option would be to have a reaper thread that is periodically harvesting expired keys and their associated values to reclaim memory but this requires more careful thread safe design.
    - In the current implementation the LRU Cache is not thread-safe.
    - It is implemented using a doubly linked list + hash table. The hash table support O(1) lookup/insertion/deletion of keys. The hash table maps keys to node object references. The node objects that have the key and value are stored in a doubly linked list to support O(1) removal (lookups, expired keys), move-to-head operations (successful lookups or when getting the data from the redis store) as well as remove-from-tail operations to maintain the maximum size requirement. 


## Code

### Complexity


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

### Benchmarking

## Unimplemented

- Concurrent LRU Cache: Bonus feature was not implemented due to lack of time.
- Redis protocol:  Bonus feature was not implemented due to lack of time.

## Known Issues / Areas for Improvement
- Fix issue with graceful shutdown of the HTTP server causing container take longer to shutdown.
- Add pre-commit git hooks for PEP8 linter
- Improve the unit and system tests.
- Improve the code documentation.
- Add logging.
- Dump http server/lrucache/db metrics to a stats database (that can be aggregated across multiple cache partitions/shards) and displayed in something like a Grafana dashboard.
- Add a _GET /stats_ route to retrieve the current HTTP server, LRUCache and DB stats. Should have its own (more aggressive) limiter so that most of the processing horsepower is reserved for the cache lookups.
- Ideally there should be authn (TLS/HTTPS) and authz if this is an external facing API or even inadvertently exposing internal APIs arising from network firewall policy errors. TLS will require lot more servers to handle the same query load as non-secure HTTP and will have higher latency.


## Time spent

Around 35 hrs were spent on this project.
- 50% was spent on reading up docs for Docker, Redis and Python APIs, preparing the dev environment. Some of this overlapped with architecture planning.
- 20% of time was spent on setting up dev environment, doing mini POCs / experimental code evaluation to decide what paradigm, 3rd party tools to use for the implementation. A lot of it involved doing mini benchmarking that also tied into the design and implementation. (A VM disk corruption triggerd by WIndows update forced reboot also required recreating the entire dev environment, Murphy's Law :))
- 15% of the time was spent on doing the actual code and unit test development using the experimental code as a base and refactoring, cleaning up hacks/shortcuts in POC code.
- 10% of the time was spent on system test and getting docker networking to play nice.
- 5% of the time was spent on documentation.
