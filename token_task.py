"""
token_task.py -- Logic for `inv token`.

Kept separate so tasks.py stays free of complex string escaping.
"""

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).parent
SRC = HERE / "src"
CONFIG = HERE / "config" / "config.yml"


def run(scope, user_id, username, step_up, ttl, list_scopes):
    sys.path.insert(0, str(SRC))

    import jwt
    import yaml

    from settings import Settings

    settings = Settings()
    SECRET = settings.SECRET_KEY
    ALGO = settings.ALGORITHM

    with open(CONFIG) as f:
        raw = yaml.safe_load(f)

    valid_scopes = {}
    for ttype, tdata in raw.get("token_types", {}).items():
        for op, op_data in tdata.get("scopes", {}).items():
            valid_scopes[f"{ttype}:{op}"] = op_data

    if list_scopes:
        print("\nValid scopes (token_type:operation):\n")
        for s, d in sorted(valid_scopes.items()):
            rpm = d.get("rate_limit_per_minute")
            cost = d.get("token_cost_base")
            print(f"  {s:<30} rpm={rpm}, cost_base={cost}")
        print()
        return

    if scope not in valid_scopes:
        print(f"\nERROR: {scope!r} is not a valid scope.")
        print("Run 'inv token --list-scopes' to see all valid scopes.\n")
        sys.exit(1)

    now = datetime.now(timezone.utc)
    expire = now + timedelta(minutes=ttl)
    payload = {
        "sub": user_id,
        "username": username,
        "scope": scope,
        "step_up": step_up,
        "iat": int(now.timestamp()),
        "exp": expire,
    }

    encoded = jwt.encode(payload, SECRET, algorithm=ALGO)
    scope_cfg = valid_scopes[scope]
    bar = "=" * 62

    print()
    print(bar)
    print("  Token issued")
    print(bar)
    print(f"  scope    : {scope}")
    print(f"  user_id  : {user_id}")
    print(f"  username : {username}")
    print(f"  step_up  : {step_up}")
    print(f"  ttl      : {ttl} min  (expires {expire.strftime('%H:%M:%S UTC')})")
    print(f"  rpm      : {scope_cfg.get('rate_limit_per_minute')}")
    print(f"  cost_base: {scope_cfg.get('token_cost_base')}")
    print(bar)
    print()
    print(encoded)
    print()
    print("--- curl example ---")
    print('curl -H "Authorization: Bearer ' + encoded + '" http://127.0.0.1:8000/api/user/1')
    print()
