FROM python:3-alpine

WORKDIR /usr/src/app
ADD src .
COPY config.sample.ini config.ini

RUN pip install -r requirements.txt

CMD ["python3", ".", "--config","config.ini"]
