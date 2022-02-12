import asyncio
from aiohttp import web

# Enable for debug logs
#logging.basicConfig(level=logging.DEBUG)

class AsyncHTTPServer:
    '''Async IO based Http server that will run a non-blocking event loop
    to serve requests querying the caching proxy/db.

    It should be run() on its own thread, separate from the main thread.
    
    Incoming requests that need to be handled will be executed on a separate
    threadpool managed by the req_executor. This allows the requests to call
    blocking code that would otherwise hold up the event loop of the server.
    '''

    def __init__(self, host, port, cache_getter, cache_req_executor, limiter):
        self.host = host
        self.port = port
        self.cache_getter = cache_getter
        self.cache_req_executor = cache_req_executor
        self.limiter = limiter
        self.loop = asyncio.new_event_loop()
        self.app = web.Application()
        self.runner = self._configure()

    def run(self):
        '''Entry point for the thread to start the server.
        '''
        asyncio.set_event_loop(self.loop)
        self.loop.run_until_complete(self.runner.setup())
        server = web.TCPSite(self.runner, self.host, self.port)
        self.loop.run_until_complete(server.start())
        self.loop.run_forever()

    # TODO: Need to fix clean shutdown
    def stop(self):
        self.loop.stop()
        #await self.loop.run_until_complete(self.runner.cleanup())        

    def is_running(self):
        return self.loop.is_running()

    #------------------------------------------------------------
    # Route handlers
    # -----------------------------------------------------------

    async def _cache_lookup(self, request):
        status = 200
        
        try:
            key = request.rel_url.query['key']
        except KeyError:
            # Bad request
            status = 400
            data = dict(key=None, value=None, status=status)
            return web.json_response(data, status=status)

        if self.limiter.is_throttling():
            # Rate limiter kicked in
            status = 503
            data = dict(key=key, value=None, status=status)
            return web.json_response(data, status=status)

        task = self.loop.run_in_executor(self.cache_req_executor,
                self.cache_getter, key)
        completed, pending = await asyncio.wait([task])
        result = task.result()
        # key may not be present in db or cache
        status = 404 if result is None else 200
        data = dict(key=key, value=result, status=status)   
        return web.json_response(data, status=status)

    def _configure(self):
        self.app.add_routes([
            web.get('/lookup', self._cache_lookup)
        ])
        return web.AppRunner(self.app)

