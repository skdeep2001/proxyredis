import aiohttp
import asyncio
import time

async def _get_value(session, url):
    '''Response processing.
    '''
    async with session.get(url) as resp:
        return await resp.json()

async def _async_run_queries(urls, results):
    '''Dispatcher for client URL requests
    '''
    async with aiohttp.ClientSession() as session:
        tasks = []
        for url in urls:
            tasks.append(asyncio.ensure_future(_get_value(session, url)))
        responses = await asyncio.gather(*tasks)
        results.extend(responses)

def run_queries(urls, results):
    #start_time = time.time()
    asyncio.run(_async_run_queries(urls, results))
    #print("--- %s seconds ---" % (time.time() - start_time))
