// Separate bootstrap: create registry and managed identity before pushing image.
// A06 must push an immutable digest before main.bicep is evaluated for deployment.
targetScope = 'resourceGroup'
@allowed(['nonprod', 'prod'])
param environment string
param prefix string
param location string = resourceGroup().location
param acrPrivateEndpointSubnetId string
param acrPrivateDnsZoneId string

var acrName = toLower(replace('${prefix}${environment}acr', '-', ''))
var identityName = '${prefix}-${environment}-runtime'

resource identity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: identityName
  location: location
}
resource acr 'Microsoft.ContainerRegistry/registries@2023-07-01' = {
  name: acrName
  location: location
  sku: { name: 'Premium' }
  properties: {
    adminUserEnabled: false
    publicNetworkAccess: 'Disabled'
  }
}
resource acrPull 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(acr.id, identity.id, 'AcrPull')
  scope: acr
  properties: {
    principalId: identity.properties.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '7f951dda-4ed3-4680-a7ca-43fe172d538d')
  }
}
resource acrEndpoint 'Microsoft.Network/privateEndpoints@2024-05-01' = {
  name: '${acrName}-pe'
  location: location
  properties: {
    subnet: { id: acrPrivateEndpointSubnetId }
    privateLinkServiceConnections: [{
      name: 'registry'
      properties: { privateLinkServiceId: acr.id, groupIds: ['registry'] }
    }]
  }
}
resource acrDns 'Microsoft.Network/privateEndpoints/privateDnsZoneGroups@2024-05-01' = {
  name: 'default'
  parent: acrEndpoint
  properties: { privateDnsZoneConfigs: [{ name: 'registry', properties: { privateDnsZoneId: acrPrivateDnsZoneId } }] }
}
output acrLoginServer string = acr.properties.loginServer
output runtimeIdentityPrincipalId string = identity.properties.principalId
