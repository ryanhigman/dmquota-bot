# DMquota Bot — container image
FROM python:3.12-slim
WORKDIR /app
RUN pip install --no-cache-dir -U discord.py
COPY dmquota_bot.py .
# -u = unbuffered, so `docker logs` shows the bot's prints immediately
CMD ["python", "-u", "dmquota_bot.py"]
