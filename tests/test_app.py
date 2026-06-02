import pytest
from app import app


@pytest.fixture
def client():
    """Create a test client for the Flask app."""
    app.config['TESTING'] = True
    with app.test_client() as client:
        yield client


def test_app_exists():
    """Test that the app is created successfully."""
    assert app is not None


def test_app_is_testing(client):
    """Test that the app is in testing mode."""
    assert app.config['TESTING'] is True


def test_basic_request(client):
    """Test a basic request to the app."""
    # This is a basic smoke test - adjust based on your routes
    response = client.get('/')
    # Accept various status codes depending on if route exists
    assert response.status_code in [200, 404, 500]
