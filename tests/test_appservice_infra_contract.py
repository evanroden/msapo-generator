"""Offline invariants, not a substitute for Azure Bicep build or ARM what-if."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INFRA = ROOT / 'infra' / 'azure'
MAIN = (INFRA / 'main.bicep').read_text()
FOUNDATION = (INFRA / 'foundation.bicep').read_text()


def test_classic_container_contract_and_minimal_replica():
    assert "linuxFxVersion: 'DOCKER|" in MAIN
    assert "name: 'WEBSITES_PORT', value: '8501'" in MAIN
    assert "healthCheckPath: '/_stcore/health'" in MAIN
    assert "name: 'WEBSITES_ENABLE_APP_SERVICE_STORAGE', value: 'false'" in MAIN
    assert 'sitecontainers@' not in MAIN.lower()
    assert 'targetPort:' not in MAIN
    assert 'capacity: 1' in MAIN
    assert "http20Enabled: false" in MAIN
    assert "name: 'authsettingsV2'" in MAIN
    assert "unauthenticatedClientAction: 'RedirectToLoginPage'" in MAIN
    assert 'excludedPaths: []' in MAIN


def test_no_implicit_storage_approval_or_public_ingress():
    assert 'param enableQualifiedFilesMount bool = false' in MAIN
    assert 'if (enableQualifiedFilesMount)' in MAIN
    assert "param dataDir string = '/mounts/msapo'" in MAIN
    assert "publicNetworkAccess: 'Disabled'" in MAIN
    assert "vnetImagePullEnabled: true" in MAIN
    assert 'secure()' in MAIN
    assert 'accessKey: storageMountKey' in MAIN
    assert 'privateEndpoints@' in MAIN
    assert 'sitecontainers' not in FOUNDATION
    assert "publicNetworkAccess: 'Disabled'" in FOUNDATION


def test_env_parameters_separate_and_unapproved():
    for env in ('nonprod', 'prod'):
        params = json.loads((INFRA / f'{env}.parameters.json').read_text())['parameters']
        foundation_params = json.loads((INFRA / f'{env}.foundation.parameters.json').read_text())['parameters']
        assert params['environment']['value'] == foundation_params['environment']['value'] == env
        assert params['enableQualifiedFilesMount']['value'] is False
        assert params['imageDigest']['value'].startswith('REPLACE_')
        assert params['allowedGroupObjectIds']['value'][0].startswith('REPLACE_')
        assert 'storageMountKey' not in params
        assert all(key in foundation_params for key in ('prefix', 'acrPrivateEndpointSubnetId', 'acrPrivateDnsZoneId'))
    nonprod = json.loads((INFRA / 'nonprod.parameters.json').read_text())['parameters']
    prod = json.loads((INFRA / 'prod.parameters.json').read_text())['parameters']
    assert nonprod['allowedGroupObjectIds'] != prod['allowedGroupObjectIds']
