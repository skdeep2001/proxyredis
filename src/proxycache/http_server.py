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
        try:
            key = request.rel_url.query['key']
        except:
            # Bad request
            return web.Response(status=400)

        if self.limiter.is_throttling():
            # Rate limiter kicked in
            return web.Response(status=503)

        task = self.loop.run_in_executor(self.cache_req_executor,
                self.cache_getter, key)
        completed, pending = await asyncio.wait([task])
        result = task.result()

        if result is None:
            return web.Response(status=404)
        else:
            return web.Response(text=result)

    def _configure(self):
        self.app.add_routes([
            web.get('/lookup', self._cache_lookup)
        ])
        return web.AppRunner(self.app)

