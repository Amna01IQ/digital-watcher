"""Download a web page and reduce it to its main visible text."""
import requests
from bs4 import BeautifulSoup

USER_AGENT = "DigitalWatcher/1.0 (+https://github.com)"


def fetch_text(url, timeout=20):
    """Download a page and return its visible text as a list of non-empty lines."""
    response = requests.get(url, timeout=timeout, headers={"User-Agent": USER_AGENT})
    response.raise_for_status()

    soup = BeautifulSoup(response.text, "html.parser")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()

    raw_text = soup.get_text(separator="\n")
    lines = [line.strip() for line in raw_text.splitlines()]
    return [line for line in lines if line]
