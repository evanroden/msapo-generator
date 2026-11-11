// A04 preparation only. Wire into A03's approved per-environment App Service IaC.
// Do not deploy until ENFRA IAM approves tenant, application, assignment and roles.
// The app registration, enterprise service principal and app roles are separately
// controlled by ENFRA IAM; this module does NOT create or assign them.
@description('Existing App Service site in this resource group (not a Container App).')
param siteName string

@description('ENFRA-approved single-tenant directory GUID; supplied by secure IaC parameters.')
param tenantId string

@description('App registration client GUID in this environment; secure IaC parameters.')
param clientId string

@description('Name ONLY of an app setting backed by an approved Key Vault reference.')
param entraClientSecretSettingName string = 'MICROSOFT_PROVIDER_AUTHENTICATION_SECRET'

resource site 'Microsoft.Web/sites@2022-09-01' existing = {
  name: siteName
}

resource auth 'Microsoft.Web/sites/config@2022-09-01' = {
  parent: site
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
      // App Service Health Check integrates with Easy Auth. Do not exempt
      // Streamlit health, websockets, uploads, downloads or static asset routes.
      excludedPaths: []
    }
    httpSettings: {
      requireHttps: true
    }
    identityProviders: {
      azureActiveDirectory: {
        enabled: true
        registration: {
          clientId: clientId
          clientSecretSettingName: entraClientSecretSettingName
          openIdIssuer: 'https://login.microsoftonline.com/${tenantId}/v2.0'
        }
      }
    }
    login: {
      tokenStore: {
        enabled: true
      }
      cookieExpiration: {
        convention: 'IdentityProviderDerived'
      }
    }
  }
}
