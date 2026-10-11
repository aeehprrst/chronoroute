"""Run the preregistered targeted hard-failure campaign."""
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from policy_campaign import main
if __name__=='__main__':raise SystemExit(main(experiment='E04'))
