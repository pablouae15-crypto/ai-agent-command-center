from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
SHARED_ENGINE = Path('D:/Shared-Local-Execution-Engine')
if str(SHARED_ENGINE) not in sys.path:
    sys.path.insert(0, str(SHARED_ENGINE))

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
