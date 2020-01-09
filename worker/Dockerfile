FROM tensorflow/tensorflow:1.15.0-gpu-py3
LABEL authors="Alexander Zhang"

RUN apt-get update && \
    apt-get install -y aria2 wget && \
	apt-get -y autoremove && \
	rm -rf /var/lib/apt/lists/*

ENV REPO_URL https://github.com/aidungeon/aidungeon/tarball/339a537

COPY . /
RUN pip install aioredis discord.py
RUN curl -LJ "$REPO_URL" | tar xz --strip-components=1 && ./download_model.sh
RUN pip install --no-cache-dir -r requirements.txt
