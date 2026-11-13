// PREPARATION ONLY. Disabled and not deployed by default.
// Intended for HealthCheckStatus, Http5xx, MemoryWorkingSet or plan CPU metrics.
// Confirm metrics supported by exact target resource and units before enabling.
@description('Exact App Service or plan ARM ID, from approved inventory.')
param targetResourceId string
@description('Name of Azure Monitor metric alert.')
param alertName string
@description('Metric namespace, e.g. Microsoft.Web/sites.')
param metricNamespace string = 'Microsoft.Web/sites'
@description('Azure metric name, e.g. HealthCheckStatus, Http5xx, MemoryWorkingSet.')
param metricName string
@description('Metric aggregation supported by the selected metric.')
@allowed(['Average','Maximum','Minimum','Total','Count'])
param aggregation string = 'Average'
@description('GreaterThan, GreaterThanOrEqual, LessThan, LessThanOrEqual.')
@allowed(['GreaterThan','GreaterThanOrEqual','LessThan','LessThanOrEqual'])
param comparison string = 'GreaterThan'
@description('Threshold in native Azure metric units: verify bytes versus GiB.')
param threshold int
@description('Reviewed action group IDs, never literal contacts or destinations.')
param actionGroupIds array = []
param severity int = 2
@description('Do not set true during preparation.')
param deployRule bool = false
@description('Do not set true until approved and smoke-tested.')
param enableAlert bool = false

resource metricRule 'Microsoft.Insights/metricAlerts@2018-03-01' = if (deployRule) {
  name: alertName
  location: 'global'
  properties: {
    description: 'MSAPO platform metric; proposed thresholds require baseline.'
    enabled: enableAlert
    severity: severity
    scopes: [
      targetResourceId
    ]
    evaluationFrequency: 'PT5M'
    windowSize: 'PT15M'
    autoMitigate: true
    criteria: {
      'odata.type': 'Microsoft.Azure.Monitor.SingleResourceMultipleMetricCriteria'
      allOf: [
        {
          name: 'metricThreshold'
          criterionType: 'StaticThresholdCriterion'
          name: 'metricThreshold'
          metricName: metricName
          metricNamespace: metricNamespace
          timeAggregation: aggregation
          operator: comparison
          threshold: threshold
        }
      ]
    }
    actions: [for id in actionGroupIds: {
      actionGroupId: id
    }]
  }
}
