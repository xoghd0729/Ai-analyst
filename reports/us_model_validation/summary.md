# US Dividend-Cut Model Validation

## Dataset

- Rows: 433
- Tickers: 87
- Years: 2021-2025
- Dividend cuts: 18 (4.2%)

### Cuts By Year

| year | cuts | rows | cut_rate |
| --- | ---: | ---: | ---: |
| 2021 | 5 | 86 | 5.8% |
| 2022 | 1 | 86 | 1.2% |
| 2023 | 1 | 87 | 1.1% |
| 2024 | 7 | 87 | 8.0% |
| 2025 | 4 | 87 | 4.6% |

### Missingness By Year

| year | payout | fcf | coverage | shareholder_yield | net_debt_ebitda | dps_yoy |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 2021 | 100.0% | 100.0% | 100.0% | 96.5% | 100.0% | 0.0% |
| 2022 | 9.3% | 5.8% | 5.8% | 5.8% | 25.6% | 0.0% |
| 2023 | 3.4% | 0.0% | 0.0% | 0.0% | 20.7% | 0.0% |
| 2024 | 4.6% | 0.0% | 0.0% | 0.0% | 20.7% | 0.0% |
| 2025 | 5.7% | 0.0% | 0.0% | 0.0% | 19.5% | 0.0% |

## Key Finding

- The full XGBoost model performs extremely well because `dps_yoy_pct` is very close to the label definition.
- This is useful as an early warning signal, but it is not enough to claim that the model learned deep financial distress.
- The no-DPS-YoY ablation is the honest stress test: it shows how much predictive power remains from payout, FCF coverage, leverage, and shareholder yield.

## Expanding Holdout Results

| test_year | model | test_cuts | AUC | PR-AUC | F1 | precision | recall | FP | FN |
| ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 2022 | xgb_full | 1 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 0 | 0 |
| 2022 | xgb_no_dps_yoy | 1 | 0.806 | 0.050 | 0.091 | 0.048 | 1.000 | 20 | 0 |
| 2022 | rule_dps_yoy_lt_minus_5 | 1 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 0 | 0 |
| 2022 | rule_payout_gt_100 | 1 | 0.494 | 0.012 | 0.000 | 0.000 | 0.000 | 1 | 1 |
| 2022 | rule_coverage_lt_1 | 1 | 0.382 | 0.012 | 0.000 | 0.000 | 0.000 | 20 | 1 |
| 2022 | rule_combo_accounting | 1 | 0.765 | 0.048 | 0.000 | 0.000 | 0.000 | 20 | 1 |
| 2023 | xgb_full | 1 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 0 | 0 |
| 2023 | xgb_no_dps_yoy | 1 | 0.767 | 0.048 | 0.000 | 0.000 | 0.000 | 2 | 1 |
| 2023 | rule_dps_yoy_lt_minus_5 | 1 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 0 | 0 |
| 2023 | rule_payout_gt_100 | 1 | 0.483 | 0.011 | 0.000 | 0.000 | 0.000 | 3 | 1 |
| 2023 | rule_coverage_lt_1 | 1 | 0.378 | 0.011 | 0.000 | 0.000 | 0.000 | 21 | 1 |
| 2023 | rule_combo_accounting | 1 | 0.756 | 0.045 | 0.000 | 0.000 | 0.000 | 21 | 1 |
| 2024 | xgb_full | 7 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 0 | 0 |
| 2024 | xgb_no_dps_yoy | 7 | 0.444 | 0.117 | 0.182 | 0.250 | 0.143 | 3 | 6 |
| 2024 | rule_dps_yoy_lt_minus_5 | 7 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 0 | 0 |
| 2024 | rule_payout_gt_100 | 7 | 0.553 | 0.105 | 0.182 | 0.250 | 0.143 | 3 | 6 |
| 2024 | rule_coverage_lt_1 | 7 | 0.667 | 0.134 | 0.267 | 0.174 | 0.571 | 19 | 3 |
| 2024 | rule_combo_accounting | 7 | 0.882 | 0.503 | 0.267 | 0.174 | 0.571 | 19 | 3 |
| 2025 | xgb_full | 4 | 1.000 | 1.000 | 0.889 | 0.800 | 1.000 | 1 | 0 |
| 2025 | xgb_no_dps_yoy | 4 | 0.435 | 0.072 | 0.000 | 0.000 | 0.000 | 3 | 4 |
| 2025 | rule_dps_yoy_lt_minus_5 | 4 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 0 | 0 |
| 2025 | rule_payout_gt_100 | 4 | 0.494 | 0.046 | 0.000 | 0.000 | 0.000 | 1 | 4 |
| 2025 | rule_coverage_lt_1 | 4 | 0.504 | 0.046 | 0.080 | 0.048 | 0.250 | 20 | 3 |
| 2025 | rule_combo_accounting | 4 | 0.812 | 0.245 | 0.080 | 0.048 | 0.250 | 20 | 3 |

## Interpretation For Presentation

- Full model average expanding-holdout AUC: 1.000
- No-DPS-YoY model average expanding-holdout AUC: 0.613
- If full >> no-DPS-YoY, explain that the current US model is strongest at detecting already-visible dividend trend breaks.
- The next improvement is to predict cuts before the DPS decline appears, using payout stress, FCF coverage, leverage, earnings trend, and sector context.

## Recommended Capstone Framing

This project is a full-stack decision-support system. The model is not presented as an oracle; it combines ML risk, financial rules, news events, and LLM-generated thesis text. The validation step explicitly exposes model leakage risk and guides the next iteration.
