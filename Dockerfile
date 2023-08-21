FROM python:3.10-alpine

WORKDIR /app

ADD ./requirements.txt /app/
RUN pip --no-cache-dir install -r requirements.txt
ADD ./torrentbot /app/torrentbot

ENTRYPOINT ["python", "-m", "torrentbot.main"]
CMD [""]
