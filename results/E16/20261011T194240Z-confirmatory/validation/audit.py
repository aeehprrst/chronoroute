"""Verify committed E16 aggregate provenance and record required checks."""
import csv
import gzip
import json
from pathlib import Path
import re
import shutil
import sys
from chronoroute import __version__,labels,provenance

root=Path(sys.argv[1]).resolve()
with provenance.RunTimer() as timer:
    manifest=provenance.validate_manifest(root/'manifest.json')
    assert manifest['dirty'] is False
    verdict=json.loads((root/'verdict.json').read_text())
    assert verdict['complete'] and verdict['deterministic_gate_passed']
    inventory=list(csv.DictReader((root/'inventory.csv').open()))
    assert len(inventory)==148 and all(r['status']=='ok' for r in inventory)
    records=json.loads((root/'per_run.json').read_text())
    deterministic=[r for r in records if not r['stochastic']]
    assert len(deterministic)==4
    summary=list(csv.DictReader((root/'summary.csv').open()))
    assert len(summary)==16 and all(int(r['n'])==36 and r['complete']=='True' for r in summary)
    with gzip.open(root/'producer-manifests.jsonl.gz','rt') as fh:
        producers=[json.loads(line) for line in fh]
    for r in producers:
        m=r['manifest']
        assert m['dirty'] is False and m['git_sha']==manifest['git_sha']
        assert provenance.file_sha256(r['path'])==r['sha256']
    validation=root/'validation';validation.mkdir(exist_ok=False)
    sources={'implementation-make-check.log':'/tmp/chronoroute-e16-code-make-check.log',
        'final-make-check.log':'/tmp/chronoroute-e16-final-make-check.log',
        'ns3-test.log':'/tmp/chronoroute-e16-final-ns3-test.log',
        'implementation-ns3-test.log':'/tmp/chronoroute-e16-ns3-test.log',
        'targeted-tests.log':'/tmp/chronoroute-e16-targeted.log',
        'tests-first-red.log':'/tmp/chronoroute-e16-red.log',
        'dead-next-red.log':'/tmp/chronoroute-e16-dead-next-red.log',
        'campaign.log':'/tmp/chronoroute-e16-campaign.log'}
    for name,source in sources.items():shutil.copyfile(source,validation/name)
    checks={}
    for name in ('implementation-make-check.log','final-make-check.log'):
        text=(validation/name).read_text()
        passed=re.search(r'(\d+) passed in ([\d.]+)s',text)
        assert passed and 'golden: spec/golden is reproducible' in text
        checks[name]=dict(passed=int(passed[1]),pytest_wall_s=float(passed[2]),golden_reproducible=True)
    text=(validation/'ns3-test.log').read_text()
    assert '1 of 1 tests passed (1 passed, 0 skipped, 0 failed, 0 crashed' in text
    assert './ns3 build -j8' in text
    checks['ns3-test.log']=dict(suites_passed=1,suites_failed=0,build_jobs=8)
    audit=dict(label='DERIVED verification of REAL code outputs and MODELLED replay results',
        source_commit=manifest['git_sha'],clean_scientific_producers=len(producers),
        deterministic_packets_per_engine={engine:sum(r[engine]['sent'] for r in deterministic) for engine in ('python','ns3')},
        stochastic_pairs=len(records)-len(deterministic),runs_per_cell=sorted({int(r['n']) for r in summary}),
        equivalent_endpoints=sum(r['equivalent']=='True' for r in summary),
        checks=checks,verdict=verdict)
    (validation/'audit.json').write_text(json.dumps(audit,indent=2)+'\n')
    (validation/'README.md').write_text('Validation logs and provenance audit for E16. The red logs record expected failures before implementation and the dead-next-link fix. Final required checks passed; audit.json contains observed counts. Scientific outcomes are MODELLED and comparison statistics DERIVED.\n')
    shutil.copyfile(__file__,validation/'audit.py')
provenance.write_manifest(validation,tool='E16 validation audit',tool_version=__version__,
    command=[sys.executable,'-B',str(Path(__file__).resolve()),str(root)],
    config={'source_commit':manifest['git_sha'],'commands':[['make','check'],['make','ns3-test','NS3_JOBS=8']]},
    seeds=[],outputs=sorted(p for p in validation.iterdir() if p.is_file()),
    labels=labels.pick('tcrh_header_bytes','routes_and_budgets','traffic_probes','link_rate_and_queues'),
    extra={'input_manifest':{'path':str(root/'manifest.json'),'sha256':provenance.file_sha256(root/'manifest.json')}},timer=timer)
provenance.validate_manifest(validation/'manifest.json')
provenance.validate_manifest(root/'manifest.json')
print(json.dumps(audit,indent=2))
