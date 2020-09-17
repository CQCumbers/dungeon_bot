FROM tensorflow/tensorflow:1.15.2-gpu-py3
LABEL authors="Alexander Zhang"

RUN apt-get update && \
    apt-get install -y aria2 wget && \
	apt-get -y autoremove && \
	rm -rf /var/lib/apt/lists/*

ENV REPO_URL https://github.com/aidungeon/aidungeon/tarball/591f318

RUN curl -LJ "$REPO_URL" | tar xz --strip-components=1 && ./download_model.sh
RUN pip install gsutil numpy profanityfilter pyyaml regex tracery
RUN pip install aioredis discord.py
COPY process_queue.py /
