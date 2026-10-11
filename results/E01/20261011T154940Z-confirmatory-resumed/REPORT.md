# E1 preregistered detection results

Network outcomes are MODELLED; statistics and routes are DERIVED. C5 uses REAL public CelesTrak elements; C2 elements and positions are MODELLED. Starlink operational routing is UNKNOWN; Starlink does not use T-CRH.

Completion and null controls: see `verdict.json` and `inventory.csv`. Per-run denominators, fault losses before a checker, undefined exposures, censoring and tail eligibility are retained in `per_run.csv` and `summary.csv`.

Operating constraints (pooled fault-clean counts plus each twin once, bootstrap over seeds):

* C5: FPR 0.005862, 95% CI [0.004974, 0.006786]; interval below the registered limit.
* C2: FPR 0.004134, 95% CI [0.003261, 0.005039]; interval below the registered limit.

Material losses under the fixed Holm families:

* C5 rate-0.3-middle, versus ls_d, detected: ChronoRoute minus comparator -0.611111; adjusted p=1.43124e-06.
* C5 rate-0.3-middle, versus lq, detected: ChronoRoute minus comparator -1.000000; adjusted p=0.
* C5 rate-0.3-first, versus lq, detected: ChronoRoute minus comparator -0.750000; adjusted p=6.20031e-10.
* C5 rate-0.3-last, versus ls_d, detected: ChronoRoute minus comparator -0.555556; adjusted p=1.47453e-05.
* C5 rate-0.3-last, versus lq, detected: ChronoRoute minus comparator -1.000000; adjusted p=0.
* C5 delay-250000-middle, versus ls_d, detected: ChronoRoute minus comparator -0.555556; adjusted p=1.47453e-05.
* C5 delay-1000000-middle, versus ls_d, detected: ChronoRoute minus comparator -0.555556; adjusted p=1.47453e-05.
* C5 delay-4000000-middle, versus ls_d, detected: ChronoRoute minus comparator -0.472222; adjusted p=0.000310609.
* C5 delay-1000000-first, versus ls_d, detected: ChronoRoute minus comparator -0.472222; adjusted p=0.00458701.
* C5 delay-1000000-last, versus ls_d, detected: ChronoRoute minus comparator -0.444444; adjusted p=0.00075662.
* C5 arq-0.01-middle, versus ls_d, detected: ChronoRoute minus comparator -0.416667; adjusted p=0.00695887.
* C5 arq-0.01-middle, versus lq, detected: ChronoRoute minus comparator -0.416667; adjusted p=0.00178075.
* C5 arq-0.1-middle, versus lq, detected: ChronoRoute minus comparator -0.444444; adjusted p=0.00075662.
* C5 arq-0.3-middle, versus lq, detected: ChronoRoute minus comparator -0.361111; adjusted p=0.00831269.
* C5 arq-0.1-last, versus lq, detected: ChronoRoute minus comparator -0.472222; adjusted p=0.000310609.
* C2 rate-0.3-middle, versus ls_d, detected: ChronoRoute minus comparator -0.611111; adjusted p=1.43124e-06.
* C2 rate-0.3-middle, versus lq, detected: ChronoRoute minus comparator -1.000000; adjusted p=0.
* C2 rate-0.3-first, versus ls_d, detected: ChronoRoute minus comparator -0.611111; adjusted p=1.43124e-06.
* C2 rate-0.3-first, versus lq, detected: ChronoRoute minus comparator -1.000000; adjusted p=0.
* C2 rate-0.3-last, versus ls_d, detected: ChronoRoute minus comparator -0.666667; adjusted p=9.84179e-08.
* C2 rate-0.3-last, versus lq, detected: ChronoRoute minus comparator -1.000000; adjusted p=0.
* C2 delay-250000-middle, versus ls_d, detected: ChronoRoute minus comparator -0.638889; adjusted p=4.04324e-07.
* C2 delay-1000000-middle, versus ls_d, detected: ChronoRoute minus comparator -0.638889; adjusted p=4.04324e-07.
* C2 delay-4000000-middle, versus ls_d, detected: ChronoRoute minus comparator -0.638889; adjusted p=4.04324e-07.
* C2 delay-1000000-first, versus ls_d, detected: ChronoRoute minus comparator -0.472222; adjusted p=0.000310609.
* C2 delay-1000000-last, versus ls_d, detected: ChronoRoute minus comparator -0.555556; adjusted p=1.47453e-05.
* C2 arq-0.01-middle, versus ls_d, detected: ChronoRoute minus comparator -0.472222; adjusted p=0.00149703.
* C2 arq-0.1-middle, versus lq, detected: ChronoRoute minus comparator -0.611111; adjusted p=1.43124e-06.
* C2 arq-0.3-middle, versus lq, detected: ChronoRoute minus comparator -0.361111; adjusted p=0.00831269.
* C2 arq-0.1-last, versus lq, detected: ChronoRoute minus comparator -0.611111; adjusted p=1.43124e-06.
* C5 rate-0.3-middle, versus ls_d, restricted_s: ChronoRoute minus comparator 2.140100; adjusted p=7.64362e-06.
* C5 rate-0.3-middle, versus lq, restricted_s: ChronoRoute minus comparator 2.676841; adjusted p=0.
* C5 rate-0.3-first, versus ls_d, restricted_s: ChronoRoute minus comparator 1.809885; adjusted p=0.00115218.
* C5 rate-0.3-first, versus lq, restricted_s: ChronoRoute minus comparator 2.458617; adjusted p=0.
* C5 rate-0.3-last, versus ls_d, restricted_s: ChronoRoute minus comparator 1.720799; adjusted p=0.000122341.
* C5 rate-0.3-last, versus lq, restricted_s: ChronoRoute minus comparator 2.676787; adjusted p=0.
* C5 delay-250000-middle, versus ls_d, restricted_s: ChronoRoute minus comparator 2.071903; adjusted p=2.63596e-05.
* C5 delay-1000000-middle, versus ls_d, restricted_s: ChronoRoute minus comparator 2.071903; adjusted p=2.63596e-05.
* C5 delay-4000000-middle, versus ls_d, restricted_s: ChronoRoute minus comparator 1.853040; adjusted p=0.000206788.
* C5 delay-1000000-first, versus ls_d, restricted_s: ChronoRoute minus comparator 1.978507; adjusted p=0.000475852.
* C5 delay-1000000-last, versus ls_d, restricted_s: ChronoRoute minus comparator 1.457977; adjusted p=0.00353523.
* C5 arq-0.01-middle, versus ls_d, restricted_s: ChronoRoute minus comparator 1.628887; adjusted p=0.00175683.
* C5 arq-0.01-middle, versus lq, restricted_s: ChronoRoute minus comparator 1.114041; adjusted p=0.00537672.
* C5 arq-0.1-middle, versus lq, restricted_s: ChronoRoute minus comparator 1.786298; adjusted p=7.18082e-05.
* C5 arq-0.3-middle, versus lq, restricted_s: ChronoRoute minus comparator 1.679992; adjusted p=0.000245916.
* C5 arq-0.1-last, versus lq, restricted_s: ChronoRoute minus comparator 2.081780; adjusted p=8.44863e-07.
* C2 rate-0.3-middle, versus ls_d, restricted_s: ChronoRoute minus comparator 2.343969; adjusted p=1.43787e-06.
* C2 rate-0.3-middle, versus lq, restricted_s: ChronoRoute minus comparator 2.632461; adjusted p=0.
* C2 rate-0.3-first, versus ls_d, restricted_s: ChronoRoute minus comparator 2.010109; adjusted p=1.4816e-05.
* C2 rate-0.3-first, versus lq, restricted_s: ChronoRoute minus comparator 2.630700; adjusted p=0.
* C2 rate-0.3-last, versus ls_d, restricted_s: ChronoRoute minus comparator 2.384392; adjusted p=4.14807e-07.
* C2 rate-0.3-last, versus lq, restricted_s: ChronoRoute minus comparator 2.632047; adjusted p=0.
* C2 delay-250000-middle, versus ls_d, restricted_s: ChronoRoute minus comparator 2.456184; adjusted p=4.14807e-07.
* C2 delay-1000000-middle, versus ls_d, restricted_s: ChronoRoute minus comparator 2.456184; adjusted p=4.14807e-07.
* C2 delay-4000000-middle, versus ls_d, restricted_s: ChronoRoute minus comparator 2.456184; adjusted p=4.14807e-07.
* C2 delay-1000000-first, versus ls_d, restricted_s: ChronoRoute minus comparator 1.805202; adjusted p=0.000295181.
* C2 delay-1000000-last, versus ls_d, restricted_s: ChronoRoute minus comparator 2.158630; adjusted p=1.4177e-05.
* C2 arq-0.01-middle, versus ls_d, restricted_s: ChronoRoute minus comparator 1.950450; adjusted p=0.000120827.
* C2 arq-0.1-middle, versus lq, restricted_s: ChronoRoute minus comparator 2.424645; adjusted p=2.22502e-08.
* C2 arq-0.3-middle, versus lq, restricted_s: ChronoRoute minus comparator 1.717265; adjusted p=0.000177342.
* C2 arq-0.1-last, versus lq, restricted_s: ChronoRoute minus comparator 2.703903; adjusted p=1.47971e-12.

LS packet FPR/detection and O-Q detector endpoints are undefined. O-Q is a privileged delivery bound. CRH-16 is the no-detector control. E2E is unlocalised. The short runs are not a measurement of an operational constellation. City results have two replicates and are descriptive. Raw simulation records are retained locally in the ignored raw cache; the committed manifest ledger preserves producer provenance and output hashes. Reproduction requires rerunning those recorded commands.
