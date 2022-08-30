FROM huggingface/transformers-pytorch-gpu:4.21.2
LABEL authors="Alexander Zhang"

RUN apt-get update && \
    apt-get install -y git git-lfs && \
	rm -rf /var/lib/apt/lists/*

RUN git lfs install
RUN git clone https://huggingface.co/KoboldAI/fairseq-dense-2.7B
RUN pip install aiohttp disnake redis
COPY process_queue.py /
