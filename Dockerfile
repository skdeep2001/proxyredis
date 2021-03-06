
FROM python:latest as base
WORKDIR /home/app
RUN pip install redis
RUN pip install aiohttp
RUN pip install uvloop
RUN mkdir -p /home/app/proxycache
COPY src/proxycache /home/app/proxycache

FROM base as unittest
RUN pip install pytest
RUN mkdir -p /home/app/tests/unit
COPY tests/ /home/app/tests
RUN ["pytest", "-v", "tests/unit"]

FROM unittest as development
ENV PYTHONPATH=/home/app
CMD ["python", "-u", "proxycache/main.py"]

FROM development as systemtest
CMD ["pytest", "-s", "-v", "tests/system"]
