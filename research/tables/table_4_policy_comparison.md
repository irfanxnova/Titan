| Scenario ID | Class | Baseline (B1: R0) | Candidate Policy | Base Recovery (%) | Cand Recovery (%) | Recovery Delta | Base Goodput (j/s) | Cand Goodput (j/s) | Retries Delta | Lost Work Delta | Duration Change (%) |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| TB-B-001 | CLASS_B_SINGLE_WORKER_FAILURE | R0 | R1 | 100% | 100% | +0% | 87.1 | 116.1 | +0 | +0 | -26.7% |
| TB-C-001 | CLASS_C_IN_FLIGHT_FAILURE | R0 | R1 | 100% | 100% | +0% | 68.3 | 82.4 | +0 | +0 | -16.9% |
| TB-D-001 | CLASS_D_REPEATED_FAILURE | R0 | R1 | 100% | 100% | +0% | 112.3 | 142.1 | +0 | +0 | -20.5% |
| TB-E-001 | CLASS_E_RETRY_PRESSURE | R0 | R2 | 100% | 0% | -100% | 51.7 | 47.1 | -1 | +0 | -11.1% |
| TB-G-001 | CLASS_G_CAPACITY_LOSS | R0 | R1 | 100% | 100% | +0% | 93.8 | 98.2 | +0 | +0 | -5.3% |
