# External Evidence Contracts

Each evidence object contains:
- `source`
- `evidence_type`
- `adapter_status`
- `generated_at`
- `data_truth_origin`
- `license_boundary`
- `real_execution_allowed=false`
- `execution_permission`
- `raw_payload_hash`
- `normalized_payload`
- `warnings`
- `errors`
- `confidence_proxy`
- `evidence_quality_score`
- `context_tags`

Validation rules:
- missing `license_boundary` fails validation
- missing `data_truth_origin` fails validation
- `real_execution_allowed=true` fails validation
- invalid adapter outputs degrade rather than crash the pipeline
