import pytest
from app import app  # Adjust import based on your main app file

@pytest.fixture
def client():
    app.config['TESTING'] = True
    with app.test_client() as client:
        yield client

def test_app_runs(client):
    """Test that the app initializes correctly"""
    assert app is not None

def test_home_route(client):
    """Add tests for your routes"""
    response = client.get('/')
    assert response.status_code in [200, 404]  # Adjust based on your app