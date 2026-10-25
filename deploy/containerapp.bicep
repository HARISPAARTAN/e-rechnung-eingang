@description('Base name for all resources')
param name string = 'erechnung'
param location string = resourceGroup().location
@description('Full image reference, e.g. ghcr.io/harispaartan/e-rechnung-eingang:v0.2.0')
param image string
@secure()
@description('API key for X-Api-Key; stored as a container app secret')
param apiKey string
param minReplicas int = 0
param maxReplicas int = 1
param htmlMaxChars string = '1000000'

resource law 'Microsoft.OperationalInsights/workspaces@2023-09-01' = {
  name: 'law-${name}'
  location: location
  properties: {
    sku: { name: 'PerGB2018' }
    retentionInDays: 30
  }
}

resource env 'Microsoft.App/managedEnvironments@2024-03-01' = {
  name: 'cae-${name}'
  location: location
  properties: {
    appLogsConfiguration: {
      destination: 'log-analytics'
      logAnalyticsConfiguration: {
        customerId: law.properties.customerId
        sharedKey: law.listKeys().primarySharedKey
      }
    }
  }
}

resource app 'Microsoft.App/containerApps@2024-03-01' = {
  name: 'ca-${name}'
  location: location
  properties: {
    managedEnvironmentId: env.id
    configuration: {
      ingress: {
        external: true
        targetPort: 8080
        transport: 'auto'
        allowInsecure: false
      }
      secrets: [
        { name: 'api-key', value: apiKey }
      ]
    }
    template: {
      containers: [
        {
          name: 'erechnung'
          image: image
          resources: { cpu: json('1.0'), memory: '2Gi' }
          env: [
            { name: 'ERE_API_KEY', secretRef: 'api-key' }
            { name: 'ERE_HTML_MAX_CHARS', value: htmlMaxChars }
          ]
          probes: [
            {
              type: 'Startup'
              httpGet: { path: '/health', port: 8080 }
              initialDelaySeconds: 10
              periodSeconds: 5
              timeoutSeconds: 3
              failureThreshold: 36
            }
            {
              type: 'Liveness'
              httpGet: { path: '/health', port: 8080 }
              periodSeconds: 30
              timeoutSeconds: 5
              failureThreshold: 3
            }
            {
              type: 'Readiness'
              httpGet: { path: '/health', port: 8080 }
              periodSeconds: 10
              timeoutSeconds: 5
              failureThreshold: 3
            }
          ]
        }
      ]
      scale: { minReplicas: minReplicas, maxReplicas: maxReplicas }
    }
  }
}

output fqdn string = app.properties.configuration.ingress.fqdn
output appName string = app.name
