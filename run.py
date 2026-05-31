from backend.config import Settings
from backend.server import run


if __name__ == "__main__":
    run(Settings.from_env())

