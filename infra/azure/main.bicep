// A07 candidate only. No deployment until A01/A03/A05/A06 release gates are approved.
// Deploy once per isolated RG (nonprod and prod), never share authoritative stores.
// Classic DOCKER| custom container, NOT Linux sitecontainers/sidecars.
targetScope = 'resourceGroup'

@allowed([
  'nonprod'
  'prod'
])
param environment string
param location string = resourceGroup().location
param prefix string
param imageRepository string = 'msapo-generator'
@minLength(64)
@maxLength(64)
@description('Full sha256 digest without sha256: prefix; exact A06-approved image.')
param imageDigest string
param keyVaultName string
param tenantId string
param entraClientId string
@minLength(1)
param allowedGroupObjectIds string[]
param vnetIntegrationSubnetId string
param appPrivateEndpointSubnetId string
param appPrivateDnsZoneId string
@description('ENFRA approval of P1v3 (~2 vCPU / 8 GiB) sizing pending measurement.')
@allowed([
  'P1v3'
  'P2v3'
])
param appServiceSku string = 'P1v3'
@description('A03-qualified Azure Files bridge only; not safe until storage and SQLite tests pass.')
param enableQualifiedFilesMount bool = false
param storageAccountName string = ''
param storageShareName string = ''
@secure()
param storageMountKey string = ''
@description('From A03; authoritative persistent records MUST NOT use the container filesystem.')
param dataDir string = '/mounts/msapo'
@description('Reviewed form-field map from render.yaml; user values must not be committed here.')
param smartsheetFormFieldMapJson string
param aiModel string = 'claude-sonnet-4-6'

var planName = '${prefix}-${environment}-plan'
var appName = '${prefix}-${environment}-app'
var acrName = toLower(replace('${prefix}${environment}acr', '-', ''))
var identityName = '${prefix}-${environment}-runtime'
var workspaceName = '${prefix}-${environment}-logs'
var insightsName = '${prefix}-${environment}-insights'
var kvUri = 'https://${keyVaultName}.vault.azure.net/secrets/'
var kvRef = {
  anthropic: '@Microsoft.KeyVault(SecretUri=${kvUri}anthropic-api-key)'
  directors: '@Microsoft.KeyVault(SecretUri=${kvUri}expense-account-directors-json)'
  formUrl: '@Microsoft.KeyVault(SecretUri=${kvUri}smartsheet-form-url)'
  authSecret: '@Microsoft.KeyVault(SecretUri=${kvUri}entra-auth-client-secret)'
}

resource identity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' existing = {
  name: identityName
}

resource acr 'Microsoft.ContainerRegistry/registries@2023-07-01' existing = {
  name: acrName
}

resource workspace 'Microsoft.OperationalInsights/workspaces@2023-09-01' = {
  name: workspaceName
  location: location
  properties: { retentionInDays: 30 }
}

resource insights 'Microsoft.Insights/components@2020-02-02' = {
  name: insightsName
  location: location
  kind: 'web'
  properties: {
    Application_Type: 'web'
    WorkspaceResourceId: workspace.id
  }
}

resource plan 'Microsoft.Web/serverfarms@2024-04-01' = {
  name: planName
  location: location
  kind: 'linux'
  sku: {
    name: appServiceSku
    tier: 'PremiumV3'
    capacity: 1
  }
  properties: {
    reserved: true
    perSiteScaling: false
  }
}

resource app 'Microsoft.Web/sites@2024-04-01' = {
  name: appName
  location: location
  kind: 'app,linux,container'
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: { '${identity.id}': {} }
  }
  properties: {
    serverFarmId: plan.id
    httpsOnly: true
    publicNetworkAccess: 'Disabled'
    virtualNetworkSubnetId: vnetIntegrationSubnetId
    vnetRouteAllEnabled: true
    vnetImagePullEnabled: true
    keyVaultReferenceIdentity: identity.id
    siteConfig: {
      linuxFxVersion: 'DOCKER|${acr.properties.loginServer}/${imageRepository}@sha256:${imageDigest}'
      acrUseManagedIdentityCreds: true
      acrUserManagedIdentityID: identity.properties.clientId
      alwaysOn: true
      healthCheckPath: '/_stcore/health'
      http20Enabled: false
      minTlsVersion: '1.2'
      ftpsState: 'Disabled'
      scmIpSecurityRestrictionsUseMain: true
      appSettings: [
        {
          name: 'WEBSITES_PORT'
          value: '8501'
        }
        {
          name: 'WEBSITES_CONTAINER_START_TIME_LIMIT'
          value: '600'
        }
        {
          name: 'WEBSITES_ENABLE_APP_SERVICE_STORAGE'
          value: 'false'
        }
        {
          name: 'WEBSITE_HEALTHCHECK_MAXPINGFAILURES'
          value: '3'
        }
        {
          name: 'EPC_DATA_DIR'
          value: dataDir
        }
        {
          name: 'PDF_BACKEND'
          value: 'libreoffice'
        }
        {
          name: 'ANTHROPIC_MODEL'
          value: aiModel
        }
        {
          name: 'ANTHROPIC_API_KEY'
          value: kvRef.anthropic
        }
        {
          name: 'EXPENSE_ACCOUNT_DIRECTORS_JSON'
          value: kvRef.directors
        }
        {
          name: 'SMARTSHEET_FORM_URL'
          value: kvRef.formUrl
        }
        {
          name: 'SMARTSHEET_FORM_FIELD_MAP_JSON'
          value: smartsheetFormFieldMapJson
        }
        {
          name: 'SMARTSHEET_URL_PREFILL_ENABLED'
          value: 'true'
        }
        {
          name: 'SMARTSHEET_PREFILL_MAX_URL_LENGTH'
          value: '7000'
        }
        {
          name: 'SMARTSHEET_API_MODE'
          value: 'disabled'
        }
        {
          name: 'SMARTSHEET_ALLOW_CUSTOM_API_BASE'
          value: 'false'
        }
        {
          name: 'MICROSOFT_PROVIDER_AUTHENTICATION_SECRET'
          value: kvRef.authSecret
        }
        {
          name: 'APPLICATIONINSIGHTS_CONNECTION_STRING'
          value: insights.properties.ConnectionString
        }
      ]
    }
  }
}

resource auth 'Microsoft.Web/sites/config@2024-04-01' = {
  parent: app
  name: 'authsettingsV2'
  properties: {
    platform: {
      enabled: true
      runtimeVersion: '~1'
    }
    globalValidation: {
      requireAuthentication: true
      unauthenticatedClientAction: 'RedirectToLoginPage'
      redirectToProvider: 'azureactivedirectory'
      excludedPaths: []
    }
    identityProviders: {
      azureActiveDirectory: {
        enabled: true
        registration: {
          clientId: entraClientId
          clientSecretSettingName: 'MICROSOFT_PROVIDER_AUTHENTICATION_SECRET'
          openIdIssuer: 'https://login.microsoftonline.com/${tenantId}/v2.0'
        }
        validation: {
          defaultAuthorizationPolicy: {
            allowedPrincipals: { groups: allowedGroupObjectIds }
          }
        }
      }
    }
    httpSettings: { requireHttps: true }
    login: { tokenStore: { enabled: false } }
  }
}

// Optional; A03 must qualify permissions, locks, restart overlap and consistency.
// App Service mounts are NOT available merely by setting EPC_DATA_DIR.
resource filesMount 'Microsoft.Web/sites/config@2024-04-01' = if (enableQualifiedFilesMount) {
  parent: app
  name: 'azurestorageaccounts'
  properties: {
    msapo: {
      type: 'AzureFiles'
      accountName: storageAccountName
      shareName: storageShareName
      accessKey: storageMountKey
      mountPath: dataDir
    }
  }
}

resource appEndpoint 'Microsoft.Network/privateEndpoints@2024-05-01' = {
  name: '${appName}-pe'
  location: location
  properties: {
    subnet: { id: appPrivateEndpointSubnetId }
    privateLinkServiceConnections: [{
      name: 'appservice'
      properties: {
        privateLinkServiceId: app.id
        groupIds: ['sites']
      }
    }]
  }
}
resource appDns 'Microsoft.Network/privateEndpoints/privateDnsZoneGroups@2024-05-01' = {
  name: 'default'
  parent: appEndpoint
  properties: {
    privateDnsZoneConfigs: [{
      name: 'app'
      properties: { privateDnsZoneId: appPrivateDnsZoneId }
    }]
  }
}
resource diagnostics 'Microsoft.Insights/diagnosticSettings@2021-05-01-preview' = {
  name: '${prefix}-${environment}-diagnostics'
  scope: app
  properties: {
    workspaceId: workspace.id
    logs: [
      {
        category: 'AppServiceConsoleLogs'
        enabled: true
      }
      {
        category: 'AppServiceHTTPLogs'
        enabled: true
      }
      {
        category: 'AppServicePlatformLogs'
        enabled: true
      }
    ]
    metrics: [{
        category: 'AllMetrics'
        enabled: true
      }]
  }
}

output appResourceId string = app.id
output acrLoginServer string = acr.properties.loginServer
output runtimeIdentityPrincipalId string = identity.properties.principalId
output environmentName string = environment
