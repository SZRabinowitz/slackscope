# /// script
# requires-python = ">=3.10"
# dependencies = [
#     "python-dotenv>=1.2.1",
#     "requests>=2.32.5",
# ]
# ///
# just run `uv run slackactive.py`
import requests
import time
from dotenv import load_dotenv
import os

load_dotenv()

cookies = {"d": os.getenv("D_COOKIE")}
token = os.getenv("TOKEN")
url = "https://flawlessai.slack.com/api/users.setPresence"
data = {"token": token, "presence": "auto"}

while True:
    print(requests.post(url, cookies=cookies, data=data).text)
    time.sleep(500)
