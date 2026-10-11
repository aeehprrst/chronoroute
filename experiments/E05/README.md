E5 uses the frozen grid in experiments/PREREG.md through ../policy_campaign.py.
The tested intervention in E01/prerequisites.py invokes ordinary deviation
handling without changing actual service time or geometry. It is MODELLED
and is not a deadline false-alarm observation. Full untriggered equivalence is
tested across every policy before sharing a control. Every run is also checked
against the control for identical sends and pre-intervention paths and timings.

Run `venv/bin/python -B experiments/E05/run.py --out results/E05/<run> --workers 8
--prior results/E04/<run>` after E4, from a clean implementation commit.
Exact-domain and tolerance-adjusted stretch bounds are checked without clamping
raw diagnostics. Losses remain infinite latency. Visited-set state is reported
as MODELLED state with Python object bytes explicitly separate from wire bytes.
