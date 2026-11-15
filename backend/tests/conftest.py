import pytest
from fastapi.testclient import TestClient
from classlive.api import create_app
from classlive.config import Settings


@pytest.fixture
def client(tmp_path):
    app = create_app(Settings(workdir=tmp_path, trainer_password="test-password"))
    with TestClient(app) as test_client:
        token=test_client.post('/api/v1/auth/login', json={'username':'formateur','password':'test-password'}).json()['access_token']
        test_client.headers.update({'Authorization':f'Bearer {token}'})
        yield test_client
