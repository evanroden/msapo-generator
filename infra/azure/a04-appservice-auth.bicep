// A04 PREPARATION ONLY: existing A03-owned Linux App Service.
// Do not deploy until IAM approval, enterprise app assignments and A05 grants.
@description('Existing A03-owned App Service; environment-specific.')
param appName string

@description('Approved ENFRA tenant GUID, supplied through restricted parameters.')
@minLength(36)
@maxLength(36)
param entraTenantId string

@description('Approved single-tenant client ID, supplied through restricted parameters.')
@minLength(36)
@maxLength(36)
param entraClientId string

@description('App setting name with Key Vault reference; never the secret.')
param clientSecretSettingName string = 'ENFRA_ENTRA_CLIENT_SECRET'

resource site 'Microsoft.Web/sites@2022-09-01' existing = {
  name: appName
}

resource auth 'Microsoft.Web/sites/config@2022-09-01' = {
  parent: site
  name: 'authsettingsV2'
  properties: {
    platform: {
      enabled: true
    }
    globalValidation: {
      requireAuthentication: true
      unauthenticatedClientAction: 'RedirectToLoginPage'
      redirectToProvider: 'azureActiveDirectory'
      // Do not exempt Streamlit data routes or health; built-in Health Check
      // integrates with App Service authentication.
      excludedPaths: []
    }
    httpSettings: {
      requireHttps: true
    }
    identityProviders: {
      azureActiveDirectory: {
        enabled: true
        registration: {
          clientId: entraClientId
          clientSecretSettingName: clientSecretSettingName
          openIdIssuer: 'https://login.microsoftonline.com/${entraTenantId}/v2.0'
        }
        validation: {
          allowedAudiences: [
            entraClientId
          ]
        }
      }
    }
    login: {
      tokenStore: {
        enabled: false
      }
    }
  }
}
// A03 owns site HTTPS-only, ingress, redirect URI and Key Vault app setting.
// "Assignment required? Yes" is ENFRA Entra service principal configuration,
// NOT controlled by this Bicep child module.
