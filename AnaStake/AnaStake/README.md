# AnaStake

Minecraft Java name availability checker. Terminal UI and a local web dashboard (Phantom).
It checks names; it does not claim or change them.

## Install and run (Python 3.11+)

    python -m venv .venv
    source .venv/bin/activate          # Windows: .venv\Scripts\activate
    pip install -r requirements.txt
    pip install -e .
    python -m pytest

    python -m anastake gui             # http://127.0.0.1:8765
    python -m anastake                 # interactive menu
    python -m anastake seq-3l
    python -m anastake random-4c --count 500
    python -m anastake length --length 5 --charset letters,digits
    python -m anastake words --wordlist words.txt --append-digits 1
    python -m anastake pattern --pattern "ab??"
    python -m anastake affix --prefix mc --free 2
    python -m anastake shapes --shape palindrome --length 4
    python -m anastake pronounce --template CVCV
    python -m anastake numbers --length 4
    python -m anastake consonants --length 3
    python -m anastake import --file names.txt

Common flags: `--delay`, `--concurrency`, `--no-underscore`, `--ignore-history`,
`--max-age HOURS`, `--confirm-above N`, `--verify`, `--out DIR`, `--db PATH`, `--yes`.
Ctrl+C finishes in-flight requests and saves the position.

Environment: `ANASTAKE_TOKEN` (for `--verify`), `ANASTAKE_WEBHOOK` (Discord hits).
Output: `available.txt`, `results.csv`, `errors.txt`, `anastake.db`.

## Not included
Proxy rotation (`--proxies`) is left out on purpose: it exists here to get past the
API's per-IP limits. Requests are spaced and back off on 429 instead.

## Unverified (see anastake/config.py)
- Lookup URL, and that 200 + profile = taken, 404 + JSON error = not found.
  If real 404s look different, results show as ERROR; adjust `NOT_FOUND_BODY_KEYS`.
- Verify URL and its AVAILABLE / DUPLICATE / NOT_ALLOWED values.
- Real rate limits; the 1 s default delay is a guess.

"Likely available" means no profile was found. The name may still be blocked or in cooldown.
