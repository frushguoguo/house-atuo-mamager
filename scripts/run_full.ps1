param(
  [string]$Config = ".\\property-workflow-config.yaml"
)

python -m property_workflow.orchestration.pipeline --task full --config $Config
