
DOCKER_ENV=--env-file env

.PHONY: unittest test clean realclean

unittest:
	docker build -t unit --target unittest . && docker rmi unit 

test:
	docker-compose ${DOCKER_ENV} down && \
	docker-compose ${DOCKER_ENV} build && \
	docker-compose ${DOCKER_ENV} run start_dependencies && \
	docker-compose ${DOCKER_ENV} run tests

all: test	

clean:
	docker-compose ${DOCKER_ENV} down
	rm -f ./*/*.pyc
	rm -rf ./*/__pycache__

realclean: clean
	docker container prune -f
	docker image prune -f
