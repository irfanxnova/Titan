| Configuration | Category | Workers | Jobs | Execution Status | Recovery Outcome | Duration Mean (s) | Goodput Mean (j/s) | Recovery Rate (%) |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| stress-scale-small | concurrency_scaling | 2 | 10 | COMPLETED | CLEAN | 0.2144 s | 46.6 | 100% |
| stress-scale-medium | concurrency_scaling | 2 | 50 | COMPLETED | CLEAN | 0.2061 s | 242.6 | 100% |
| stress-scale-large | concurrency_scaling | 4 | 100 | COMPLETED | CLEAN | 0.2383 s | 419.6 | 100% |
| stress-single-failure | failure_intensity | 2 | 20 | COMPLETED | RECOVERED | 0.2998 s | 66.7 | 100% |
| stress-repeated-failure | failure_intensity | 4 | 40 | COMPLETED | RECOVERED | 0.3241 s | 123.4 | 100% |
| stress-retry-pressure | retry_pressure | 2 | 10 | COMPLETED | UNRECOVERED | 0.2902 s | 31.0 | 0% |
