// PREPARATION ONLY. Defaults create no resource. No action groups or costs are changed.
// Supply one reviewed, redacted KQL query from dashboard-queries.kql per rule.
// Do not enable until AppEvents ingestion, action group ownership, and alert firing are tested.
@description('Region for the scheduled query rule; must match ENFRA-approved location.')
param location string
@description('Existing Log Analytics workspace ARM ID; never a placeholder in a deployment.')
param workspaceResourceId string
@description('Reviewed alert resource name, e.g. msapo-save-failed.')
param alertName string
@description('KQL query yielding matching event rows, not raw document data.')
param query string
@description('Approved Azure Monitor action group ARM IDs. Leave empty until formally approved.')
param actionGroupIds array = []
@description('Proposed severity: 0 critical through 4 informational.')
param severity int = 2
@description('Do not set true during preparation.')
param deployRule bool = false
@description('Do not set true until routing and ingestion acceptance pass.')
param enableAlert bool = false
@description('Proposed event count threshold.')
param minEventCount int = 1

resource logRule 'Microsoft.Insights/scheduledQueryRules@2023-12-01' = if (deployRule) {
  name: alertName
  location: location
  properties: {
    displayName: alertName
    description: 'MSAPO bounded event count; requires approved routing and synthetic ingestion test.'
    enabled: enableAlert
    severity: severity
    scopes: [
      workspaceResourceId
    ]
    evaluationFrequency: 'PT5M'
    windowSize: 'PT15M'
    autoMitigate: true
    criteria: {
      allOf: [
        {
          query: query
          timeAggregation: 'Count'
          operator: 'GreaterThanOrEqual'
          threshold: minEventCount
          failingPeriods: {
            numberOfEvaluationPeriods: 1
            minFailingPeriodsToAlert: 1
          }
        }
      ]
    }
    actions: {
      actionGroups: actionGroupIds
    }
  }
}
