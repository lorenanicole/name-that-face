"""
tasks.py — Invoke task definitions for Name-that-face.

Usage:
    inv serve                  # start the FastAPI server
    inv client                 # start the Streamlit UI
    inv token                  # issue a user:read token (defaults)
    inv token --scope user:write --step-up
    inv token --scope admin:admin --step-up --ttl 60
    inv token --list-scopes    # list all valid scopes from config.yml
    inv ngrok                  # tunnel Streamlit client (:8501) via ngrok
    inv ngrok --port 8000      # tunnel the API instead
    inv ngrok --url            # print the current public URL
    inv test --unit            # unit tests only
    inv test --integration     # integration tests only
    inv test --coverage        # all tests + HTML coverage report
    inv test --verbose         # any of the above with -v
    inv lint                   # check code style with ruff
    inv fmt                    # auto-format with ruff
"""

from pathlib import Path

from invoke import task

HERE = Path(__file__).parent
SRC = HERE / "src"


@task
def serve(c):
    """Start the FastAPI server (uvicorn, hot-reload, port 8000)."""
    c.run(
        f"poetry run uvicorn app:app --app-dir {SRC} --host 127.0.0.1 --port 8000 --reload",
        pty=False,
    )


@task
def client(c):
    """Launch the Streamlit front-end (port 8501)."""
    c.run(
        f"poetry run streamlit run {SRC / 'client.py'} --server.port 8501",
        pty=False,
    )


@task(
    help={
        "port": "Local port to tunnel (default: 8501 — the Streamlit client)",
        "url": "Just print the current public URL without starting a new tunnel",
    }
)
def ngrok(c, port=8501, url=False):
    """Start an ngrok HTTPS tunnel, or print the current public URL."""
    import json
    import urllib.request

    if url:
        try:
            with urllib.request.urlopen("http://127.0.0.1:4040/api/tunnels") as resp:
                data = json.loads(resp.read())
            public_url = data["tunnels"][0]["public_url"]
            print(f"\n  {public_url}\n")
        except Exception:
            print("\n  No ngrok tunnel running. Start one with: inv ngrok\n")
        return

    c.run(f"ngrok http {port}", pty=False)


@task(
    help={
        "scope": "token_type:operation  e.g. user:read, user:write, admin:admin  (default: user:read)",
        "user-id": "JWT subject / user ID  (default: dev-user)",
        "username": "Human-readable username stored in JWT  (default: dev@name-that-face.local)",
        "step-up": "Set step_up=True -- needed for write/admin scopes  (default: False)",
        "ttl": "Token lifetime in minutes  (default: 30)",
        "list-scopes": "Print every valid token_type:operation from config.yml and exit",
    }
)
def token(
    c,
    scope="user:read",
    user_id="dev-user",
    username="dev@name-that-face.local",
    step_up=False,
    ttl=30,
    list_scopes=False,
):
    """Issue a signed JWT for local development and testing."""
    import token_task

    token_task.run(
        scope=scope,
        user_id=user_id,
        username=username,
        step_up=step_up,
        ttl=ttl,
        list_scopes=list_scopes,
    )


@task(
    help={
        "unit": "Run only @pytest.mark.unit tests",
        "integration": "Run only @pytest.mark.integration tests",
        "coverage": "Emit an HTML coverage report in htmlcov/",
        "verbose": "Pass -v to pytest for full test names",
    }
)
def test(c, unit=False, integration=False, coverage=False, verbose=False):
    """Run the test suite (unit, integration, or all)."""
    cmd = ["poetry", "run", "pytest"]

    if unit and not integration:
        cmd += ["-m", "unit"]
    elif integration and not unit:
        cmd += ["-m", "integration"]

    if coverage:
        cmd += [
            "--cov=src",
            "--cov-report=term-missing",
            "--cov-report=html:htmlcov",
        ]

    if verbose:
        cmd.append("-v")

    c.run(" ".join(cmd), pty=True)


@task
def lint(c):
    """Lint src/ and tests/ with ruff."""
    c.run("poetry run python -m ruff check src/ tests/", pty=True)


@task
def fmt(c):
    """Auto-format src/ and tests/ with ruff."""
    c.run("poetry run python -m ruff format src/ tests/", pty=True)
